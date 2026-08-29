import Foundation
import XCTest
@testable import TAMForge

@MainActor
final class ActivityArtifactUploadTests: XCTestCase {
    func testUploadStagesHashesStreamsAndCleansTemporaryCopyAfterConfirmation() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let transport = ActivityFileUploadStub()
        let uploader = ActivityArtifactUploader(api: api, transport: transport, files: ActivityStagedFileStore())

        let artifact = try await uploader.upload(
            sourceURL: source,
            activityID: 41,
            expectedVersion: 3,
            artifactClass: .writtenOutput
        )

        XCTAssertEqual(artifact.id, 90)
        XCTAssertEqual(transport.uploadedByteCounts, [5])
        XCTAssertEqual(api.presigns.first?.sha256, "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
        XCTAssertEqual(api.confirms.count, 1)
        XCTAssertTrue(transport.uploadedFiles.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testIndeterminateConfirmationReconcilesBeforeRetryingSameConfirmKey() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        api.confirmError = .network
        let uploader = ActivityArtifactUploader(api: api, transport: ActivityFileUploadStub(), files: ActivityStagedFileStore(), idempotency: { "stable-artifact-key" })

        await XCTAssertThrowsErrorAsync {
            _ = try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }
        XCTAssertEqual(uploader.state, .confirmationIndeterminate)
        XCTAssertEqual(api.confirms.first?.idempotencyKey, "stable-artifact-key")

        api.confirmError = nil
        let artifact = try await uploader.reconcile()

        XCTAssertEqual(artifact.id, 90)
        XCTAssertEqual(api.confirms.map(\.idempotencyKey), ["stable-artifact-key", "stable-artifact-key"])
    }

    func testCancellationRemovesStagedFileAndDoesNotConfirmArtifact() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let transport = ActivityFileUploadStub(error: CancellationError())
        let uploader = ActivityArtifactUploader(api: api, transport: transport, files: ActivityStagedFileStore())

        await XCTAssertThrowsErrorAsync {
            _ = try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }

        XCTAssertEqual(uploader.state, .cancelled)
        XCTAssertTrue(api.confirms.isEmpty)
        XCTAssertTrue(transport.uploadedFiles.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    private func temporaryFile(contents: Data) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try contents.write(to: url)
        return url
    }
}

@MainActor
final class ActivityFileUploadStub: ActivityPresignedUploadTransport {
    let error: Error?
    private(set) var uploadedFiles: [URL] = []
    private(set) var uploadedByteCounts: [Int] = []

    init(error: Error? = nil) {
        self.error = error
    }

    func upload(fileURL: URL, to url: URL, headers: [String: String]) async throws {
        uploadedFiles.append(fileURL)
        uploadedByteCounts.append((try? FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? Int) ?? 0)
        if let error { throw error }
    }
}

@MainActor
func XCTAssertThrowsErrorAsync(
    _ expression: () async throws -> Void,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    do {
        try await expression()
        XCTFail("Expected error", file: file, line: line)
    } catch {
    }
}
