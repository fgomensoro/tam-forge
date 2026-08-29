import CryptoKit
import Foundation
import UniformTypeIdentifiers

enum ActivityArtifactUploadState: Equatable, Sendable {
    case idle
    case preparing
    case uploading
    case confirming
    case confirmationIndeterminate
    case complete
    case cancelled
    case failed
}

@MainActor
protocol ActivityPresignedUploadTransport: AnyObject {
    func upload(fileURL: URL, to url: URL, headers: [String: String]) async throws
}

@MainActor
final class URLSessionActivityPresignedUploadTransport: ActivityPresignedUploadTransport {
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func upload(fileURL: URL, to url: URL, headers: [String: String]) async throws {
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        headers.forEach { request.setValue($0.value, forHTTPHeaderField: $0.key) }
        let (_, response) = try await session.upload(for: request, fromFile: fileURL)
        guard let response = response as? HTTPURLResponse else { throw ActivityAPIError.invalidResponse }
        guard (200...299).contains(response.statusCode) else {
            throw response.statusCode == 403 ? ActivityAPIError.expiredPresign : ActivityAPIError.network
        }
    }
}

struct ActivityStagedFile: Equatable, Sendable {
    var fileURL: URL
    var originalFilename: String
    var byteLength: Int
    var sha256: String
    var contentType: String
}

struct ActivityStagedFileStore: Sendable {
    private static let maximumBytes = 5 * 1024 * 1024 * 1024
    private static let chunkSize = 64 * 1024

    func stage(sourceURL: URL) throws -> ActivityStagedFile {
        let isScoped = sourceURL.startAccessingSecurityScopedResource()
        defer {
            if isScoped { sourceURL.stopAccessingSecurityScopedResource() }
        }

        let filename = sourceURL.lastPathComponent
        guard !filename.isEmpty, !filename.contains("/"), !filename.contains("\\") else {
            throw ActivityAPIError.invalidResponse
        }

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("TAMForgeActivityUploads", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let destination = directory.appendingPathComponent(UUID().uuidString, isDirectory: false)
        do {
            try FileManager.default.copyItem(at: sourceURL, to: destination)
            let result = try digest(fileURL: destination)
            guard result.byteLength <= Self.maximumBytes else { throw ActivityAPIError.invalidResponse }
            let contentType = UTType(filenameExtension: sourceURL.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
            return .init(
                fileURL: destination,
                originalFilename: filename,
                byteLength: result.byteLength,
                sha256: result.sha256,
                contentType: contentType
            )
        } catch {
            try? FileManager.default.removeItem(at: destination)
            throw error
        }
    }

    func remove(_ staged: ActivityStagedFile) {
        try? FileManager.default.removeItem(at: staged.fileURL)
    }

    private func digest(fileURL: URL) throws -> (sha256: String, byteLength: Int) {
        let handle = try FileHandle(forReadingFrom: fileURL)
        defer { try? handle.close() }
        var hasher = SHA256()
        var byteLength = 0
        while let chunk = try handle.read(upToCount: Self.chunkSize), !chunk.isEmpty {
            byteLength += chunk.count
            guard byteLength <= Self.maximumBytes else { throw ActivityAPIError.invalidResponse }
            hasher.update(data: chunk)
        }
        return (hasher.finalize().map { String(format: "%02x", $0) }.joined(), byteLength)
    }
}

@MainActor
final class ActivityArtifactUploader: ObservableObject {
    @Published private(set) var state: ActivityArtifactUploadState = .idle

    private struct PendingConfirmation {
        var staged: ActivityStagedFile
        var presign: ActivityArtifactPresignCommand
        var confirm: ActivityArtifactConfirmCommand
    }

    private let api: any ActivityAPI
    private let transport: any ActivityPresignedUploadTransport
    private let files: ActivityStagedFileStore
    private let idempotency: @Sendable () -> String
    private var pending: PendingConfirmation?

    init(
        api: any ActivityAPI,
        transport: any ActivityPresignedUploadTransport = URLSessionActivityPresignedUploadTransport(),
        files: ActivityStagedFileStore = .init(),
        idempotency: @escaping @Sendable () -> String = { UUID().uuidString }
    ) {
        self.api = api
        self.transport = transport
        self.files = files
        self.idempotency = idempotency
    }

    func upload(
        sourceURL: URL,
        activityID: Int,
        expectedVersion: Int,
        artifactClass: ActivityArtifactClass
    ) async throws -> ActivityArtifact {
        state = .preparing
        let staged: ActivityStagedFile
        do {
            let fileStore = files
            staged = try await Task.detached(priority: .utility) { try fileStore.stage(sourceURL: sourceURL) }.value
        } catch is CancellationError {
            state = .cancelled
            throw ActivityAPIError.cancelled
        } catch {
            state = .failed
            throw error
        }

        let key = idempotency()
        let command = ActivityArtifactPresignCommand(
            activityID: activityID,
            expectedVersion: expectedVersion,
            artifactClass: artifactClass,
            sha256: staged.sha256,
            byteLength: staged.byteLength,
            contentType: staged.contentType,
            originalFilename: staged.originalFilename,
            idempotencyKey: key
        )
        do {
            let response = try await api.presign(command)
            return try await finish(staged: staged, presign: command, response: response)
        } catch is CancellationError {
            files.remove(staged)
            state = .cancelled
            throw ActivityAPIError.cancelled
        } catch let error as ActivityAPIError where error == .cancelled {
            files.remove(staged)
            state = .cancelled
            throw error
        } catch {
            if state == .confirmationIndeterminate { throw error }
            files.remove(staged)
            state = .failed
            throw error
        }
    }

    func reconcile() async throws -> ActivityArtifact {
        guard let pending else { throw ActivityAPIError.invalidResponse }
        state = .confirmationIndeterminate
        do {
            let reconciliation = try await api.presign(pending.presign)
            if let artifactID = reconciliation.artifactID {
                let artifact = artifact(from: pending.staged, id: artifactID, artifactClass: pending.presign.artifactClass)
                complete(pending)
                return artifact
            }
            let artifact = try await api.confirm(pending.confirm)
            complete(pending)
            return artifact
        } catch is CancellationError {
            cancel()
            throw ActivityAPIError.cancelled
        } catch let error as ActivityAPIError where error == .cancelled {
            cancel()
            throw error
        } catch {
            state = .confirmationIndeterminate
            throw error
        }
    }

    func cancel() {
        if let pending { files.remove(pending.staged) }
        pending = nil
        state = .cancelled
    }

    private func finish(
        staged: ActivityStagedFile,
        presign: ActivityArtifactPresignCommand,
        response: ActivityArtifactPresignResponse
    ) async throws -> ActivityArtifact {
        if let artifactID = response.artifactID {
            let artifact = artifact(from: staged, id: artifactID, artifactClass: presign.artifactClass)
            files.remove(staged)
            state = .complete
            return artifact
        }
        guard let upload = response.upload else { throw ActivityAPIError.invalidResponse }

        state = .uploading
        do {
            try await transport.upload(fileURL: staged.fileURL, to: upload.url, headers: upload.headers)
        } catch let error as ActivityAPIError where error == .expiredPresign {
            return try await refreshExpiredPresign(staged: staged, previous: presign)
        }

        let pending = PendingConfirmation(
            staged: staged,
            presign: presign,
            confirm: .init(
                activityID: presign.activityID,
                expectedVersion: presign.expectedVersion,
                uploadIdempotencyKey: presign.idempotencyKey,
                objectKey: response.objectKey,
                idempotencyKey: presign.idempotencyKey
            )
        )
        self.pending = pending
        state = .confirming
        do {
            let artifact = try await api.confirm(pending.confirm)
            complete(pending)
            return artifact
        } catch {
            self.pending = pending
            state = .confirmationIndeterminate
            throw error
        }
    }

    private func refreshExpiredPresign(
        staged: ActivityStagedFile,
        previous: ActivityArtifactPresignCommand
    ) async throws -> ActivityArtifact {
        let refreshed = ActivityArtifactPresignCommand(
            activityID: previous.activityID,
            expectedVersion: previous.expectedVersion,
            artifactClass: previous.artifactClass,
            sha256: previous.sha256,
            byteLength: previous.byteLength,
            contentType: previous.contentType,
            originalFilename: previous.originalFilename,
            idempotencyKey: idempotency()
        )
        let response = try await api.presign(refreshed)
        return try await finish(staged: staged, presign: refreshed, response: response)
    }

    private func complete(_ pending: PendingConfirmation) {
        files.remove(pending.staged)
        self.pending = nil
        state = .complete
    }

    private func artifact(
        from staged: ActivityStagedFile,
        id: Int,
        artifactClass: ActivityArtifactClass
    ) -> ActivityArtifact {
        .init(
            id: id,
            sha256: staged.sha256,
            byteLength: staged.byteLength,
            contentType: staged.contentType,
            originalFilename: staged.originalFilename,
            artifactClass: artifactClass
        )
    }
}
