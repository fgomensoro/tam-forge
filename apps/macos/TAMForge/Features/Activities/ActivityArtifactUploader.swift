import CryptoKit
import Darwin
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
        try Task.checkCancellation()
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        headers.forEach { request.setValue($0.value, forHTTPHeaderField: $0.key) }
        let (_, response) = try await session.upload(for: request, fromFile: fileURL)
        try Task.checkCancellation()
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
    // The OS releases this advisory lock even if the app terminates unexpectedly.
    fileprivate var lease: FileHandle
}

struct ActivityStagedFileStore: Sendable {
    private static let maximumBytes = 5 * 1024 * 1024 * 1024
    private static let chunkSize = 64 * 1024
    private let directory: URL

    init(directory: URL = FileManager.default.temporaryDirectory.appendingPathComponent("TAMForgeActivityUploads", isDirectory: true)) {
        self.directory = directory
    }

    /// Call once at app startup, never as a navigation/model-creation side effect.
    @discardableResult
    func cleanupAbandonedCopies() throws -> Int {
        let manager = FileManager.default
        guard manager.fileExists(atPath: directory.path) else { return 0 }
        let metadata = try directory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard metadata.isDirectory == true, metadata.isSymbolicLink != true else { return 0 }
        var removed = 0
        for candidate in try manager.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) {
            guard UUID(uuidString: candidate.lastPathComponent) != nil else { continue }
            // Atomic, nonblocking open+lock skips copies owned by any live process.
            let descriptor = open(candidate.path, O_RDONLY | O_EXLOCK | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
            guard descriptor >= 0 else { continue }
            defer { close(descriptor) }
            var opened = stat()
            var current = stat()
            guard fstat(descriptor, &opened) == 0, opened.st_mode & S_IFMT == S_IFREG,
                  lstat(candidate.path, &current) == 0, current.st_mode & S_IFMT == S_IFREG,
                  opened.st_dev == current.st_dev, opened.st_ino == current.st_ino else { continue }
            guard unlink(candidate.path) == 0 else {
                throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
            }
            removed += 1
        }
        return removed
    }

    func stage(sourceURL: URL) throws -> ActivityStagedFile {
        try Task.checkCancellation()
        let isScoped = sourceURL.startAccessingSecurityScopedResource()
        defer {
            if isScoped { sourceURL.stopAccessingSecurityScopedResource() }
        }

        let filename = sourceURL.lastPathComponent
        guard !filename.isEmpty, !filename.contains("/"), !filename.contains("\\") else {
            throw ActivityAPIError.invalidResponse
        }
        let metadata = try sourceURL.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard metadata.isRegularFile == true, let size = metadata.fileSize, size <= Self.maximumBytes else {
            throw ActivityAPIError.invalidResponse
        }

        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let directoryMetadata = try directory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard directoryMetadata.isDirectory == true, directoryMetadata.isSymbolicLink != true else {
            throw ActivityAPIError.invalidResponse
        }
        let destination = directory.appendingPathComponent(UUID().uuidString, isDirectory: false)
        let descriptor = open(destination.path, O_CREAT | O_EXCL | O_RDWR | O_EXLOCK | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        let lease = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        do {
            let result = try copyAndDigest(sourceURL: sourceURL, output: lease)
            try Task.checkCancellation()
            let contentType = UTType(filenameExtension: sourceURL.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
            return .init(
                fileURL: destination,
                originalFilename: filename,
                byteLength: result.byteLength,
                sha256: result.sha256,
                contentType: contentType,
                lease: lease
            )
        } catch {
            try? FileManager.default.removeItem(at: destination)
            throw error
        }
    }

    func remove(_ staged: ActivityStagedFile) {
        try? FileManager.default.removeItem(at: staged.fileURL)
    }

    private func copyAndDigest(sourceURL: URL, output: FileHandle) throws -> (sha256: String, byteLength: Int) {
        try Task.checkCancellation()
        let input = try FileHandle(forReadingFrom: sourceURL)
        defer { try? input.close() }
        var hasher = SHA256()
        var byteLength = 0
        while true {
            try Task.checkCancellation()
            guard let chunk = try input.read(upToCount: Self.chunkSize), !chunk.isEmpty else { break }
            try Task.checkCancellation()
            byteLength += chunk.count
            guard byteLength <= Self.maximumBytes else { throw ActivityAPIError.invalidResponse }
            try output.write(contentsOf: chunk)
            hasher.update(data: chunk)
        }
        return (hasher.finalize().map { String(format: "%02x", $0) }.joined(), byteLength)
    }
}

@MainActor
final class ActivityArtifactUploader: ObservableObject {
    @Published private(set) var state: ActivityArtifactUploadState = .idle
    @Published private(set) var isRunning = false

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
    private var operation: Task<ActivityArtifact, Error>?

    var blocksMutations: Bool { isRunning || state == .confirmationIndeterminate }

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
        guard !blocksMutations else { throw ActivityAPIError.invalidResponse }
        return try await run {
            self.state = .preparing
            let fileStore = self.files
            let staging = Task.detached(priority: .utility) { try fileStore.stage(sourceURL: sourceURL) }
            let staged = try await withTaskCancellationHandler {
                try await staging.value
            } onCancel: {
                staging.cancel()
            }
            defer {
                withExtendedLifetime(staged) {
                    if self.pending?.staged.fileURL != staged.fileURL { fileStore.remove(staged) }
                }
            }
            try Task.checkCancellation()
            let command = ActivityArtifactPresignCommand(
                activityID: activityID, expectedVersion: expectedVersion, artifactClass: artifactClass,
                sha256: staged.sha256, byteLength: staged.byteLength, contentType: staged.contentType,
                originalFilename: staged.originalFilename, idempotencyKey: self.idempotency()
            )
            let response = try await self.api.presign(command)
            try Task.checkCancellation()
            return try await self.finish(staged: staged, presign: command, response: response)
        }
    }

    func reconcile() async throws -> ActivityArtifact {
        guard !isRunning, let pending else { throw ActivityAPIError.invalidResponse }
        return try await run {
            self.state = .confirming
            let response = try await self.api.presign(pending.presign)
            try Task.checkCancellation()
            let artifact: ActivityArtifact
            if let artifactID = response.artifactID {
                artifact = self.artifact(from: pending.staged, id: artifactID, artifactClass: pending.presign.artifactClass)
            } else {
                artifact = try await self.api.confirm(pending.confirm)
                try Task.checkCancellation()
            }
            self.complete(pending)
            return artifact
        }
    }

    /// Abandons local attachment/confirmation and temporary bytes, not server evidence.
    func cancel() {
        operation?.cancel()
        if let pending { files.remove(pending.staged) }
        pending = nil
        state = .cancelled
    }

    private func run(_ action: @escaping @MainActor () async throws -> ActivityArtifact) async throws -> ActivityArtifact {
        if Task.isCancelled {
            state = .cancelled
            throw ActivityAPIError.cancelled
        }
        isRunning = true
        let task = Task {
            try Task.checkCancellation()
            return try await action()
        }
        operation = task
        defer {
            operation = nil
            isRunning = false
        }
        do {
            return try await withTaskCancellationHandler {
                let artifact = try await task.value
                try Task.checkCancellation()
                return artifact
            } onCancel: {
                task.cancel()
            }
        } catch {
            if task.isCancelled || Task.isCancelled || error is CancellationError
                || error as? ActivityAPIError == .cancelled
                || (error as? URLError)?.code == .cancelled {
                if let pending { files.remove(pending.staged) }
                pending = nil
                state = .cancelled
                throw ActivityAPIError.cancelled
            }
            state = pending == nil ? .failed : .confirmationIndeterminate
            throw error
        }
    }

    private func finish(
        staged: ActivityStagedFile,
        presign: ActivityArtifactPresignCommand,
        response: ActivityArtifactPresignResponse,
        mayRefresh: Bool = true
    ) async throws -> ActivityArtifact {
        try Task.checkCancellation()
        if let artifactID = response.artifactID {
            state = .complete
            return artifact(from: staged, id: artifactID, artifactClass: presign.artifactClass)
        }
        guard let upload = response.upload else { throw ActivityAPIError.invalidResponse }
        state = .uploading
        do {
            try await transport.upload(fileURL: staged.fileURL, to: upload.url, headers: upload.headers)
            try Task.checkCancellation()
        } catch let error as ActivityAPIError where error == .expiredPresign && mayRefresh {
            try Task.checkCancellation()
            // Presign replay refreshes the URL for the original intent; no new intent is needed.
            let refreshed = try await api.presign(presign)
            try Task.checkCancellation()
            return try await finish(staged: staged, presign: presign, response: refreshed, mayRefresh: false)
        }
        let pending = PendingConfirmation(
            staged: staged,
            presign: presign,
            confirm: .init(
                activityID: presign.activityID, expectedVersion: presign.expectedVersion,
                uploadIdempotencyKey: presign.idempotencyKey, objectKey: response.objectKey,
                idempotencyKey: presign.idempotencyKey
            )
        )
        self.pending = pending
        state = .confirming
        try Task.checkCancellation()
        let artifact = try await api.confirm(pending.confirm)
        try Task.checkCancellation()
        complete(pending)
        return artifact
    }

    private func complete(_ pending: PendingConfirmation) {
        files.remove(pending.staged)
        self.pending = nil
        state = .complete
    }

    private func artifact(from staged: ActivityStagedFile, id: Int, artifactClass: ActivityArtifactClass) -> ActivityArtifact {
        .init(
            id: id, sha256: staged.sha256, byteLength: staged.byteLength, contentType: staged.contentType,
            originalFilename: staged.originalFilename, artifactClass: artifactClass
        )
    }
}
