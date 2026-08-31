import Foundation
import XCTest

@MainActor
final class ActivityArtifactUploadTests: XCTestCase {
    func testStartupCleanupRemovesOnlyAbandonedUUIDRegularFiles() throws {
        let root = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let directory = root.appendingPathComponent("TAMForgeActivityUploads", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        let abandoned = directory.appendingPathComponent(UUID().uuidString)
        let unrelated = directory.appendingPathComponent("keep.txt")
        let source = root.appendingPathComponent(UUID().uuidString)
        let symbolicLink = directory.appendingPathComponent(UUID().uuidString)
        let nested = directory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        for url in [abandoned, unrelated, source] { try Data("private bytes".utf8).write(to: url) }
        try FileManager.default.createSymbolicLink(at: symbolicLink, withDestinationURL: source)
        try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: false)
        let nestedFile = nested.appendingPathComponent(UUID().uuidString)
        try Data("do not recurse".utf8).write(to: nestedFile)

        let removed = try ActivityStagedFileStore(directory: directory).cleanupAbandonedCopies()

        XCTAssertEqual(removed, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: abandoned.path))
        for url in [unrelated, source, symbolicLink, nestedFile] {
            XCTAssertTrue(FileManager.default.fileExists(atPath: url.path), url.path)
        }
        XCTAssertEqual(try Data(contentsOf: source), Data("private bytes".utf8))
    }

    func testStartupCleanupSkipsActiveCopyThenRemovesItAfterOwnerReleasesIt() throws {
        let root = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("original.txt")
        try Data("hello".utf8).write(to: source)
        let directory = root.appendingPathComponent("TAMForgeActivityUploads", isDirectory: true)
        let owner = ActivityStagedFileStore(directory: directory)
        let startup = ActivityStagedFileStore(directory: directory)
        let stagedURL: URL
        do {
            let staged = try owner.stage(sourceURL: source)
            stagedURL = staged.fileURL
            try withExtendedLifetime(staged) {
                XCTAssertEqual(try startup.cleanupAbandonedCopies(), 0)
                XCTAssertTrue(FileManager.default.fileExists(atPath: stagedURL.path))
            }
        }

        XCTAssertEqual(try startup.cleanupAbandonedCopies(), 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: stagedURL.path))
        XCTAssertEqual(try Data(contentsOf: source), Data("hello".utf8))
    }

    func testStartupCleanupDoesNotFollowSymlinkedDirectoryOrCreateMissingDirectory() throws {
        let root = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let directory = root.appendingPathComponent("TAMForgeActivityUploads", isDirectory: true)
        XCTAssertEqual(try ActivityStagedFileStore(directory: directory).cleanupAbandonedCopies(), 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
        let outside = root.appendingPathComponent("originals", isDirectory: true)
        try FileManager.default.createDirectory(at: outside, withIntermediateDirectories: false)
        let original = outside.appendingPathComponent(UUID().uuidString)
        try Data("private original".utf8).write(to: original)
        try FileManager.default.createSymbolicLink(at: directory, withDestinationURL: outside)

        XCTAssertEqual(try ActivityStagedFileStore(directory: directory).cleanupAbandonedCopies(), 0)
        XCTAssertEqual(try Data(contentsOf: original), Data("private original".utf8))
    }

    func testWorkspaceBlocksMutationsUntilUploadIsReconciledOrAbandoned() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let transport = ActivityFileUploadStub()
        let uploader = ActivityArtifactUploader(api: api, transport: transport)
        let model = ActivityWorkspaceModel(activityID: 41, api: api,
                                           drafts: InMemoryActivityDraftStore(), timerJournal: InMemoryActivityTimerJournal())
        model.connect(uploader: uploader)
        await model.open()
        model.updateDraft(ActivityFixtures.completeWritingDraft(for: detail))
        model.hasAcknowledgedImmutability = true
        let gate = ActivityTestGate()
        transport.beforeUpload = { await gate.wait() }
        api.confirmError = .network
        let upload = Task { await model.upload(sourceURL: source, artifactClass: .writtenOutput) }
        await fulfillment(of: [gate.entered], timeout: 1)

        XCTAssertFalse(model.canCommit)
        await model.heartbeat(automatic: true)
        XCTAssertEqual(api.heartbeats.count, 1, "A long upload must not lose focus at the backend's 30-second cap")
        XCTAssertEqual(model.activity?.optimisticVersion, detail.optimisticVersion)
        await model.commit()
        await model.pause()
        await model.setSourceHidden(true)
        await model.classifyIncomplete(as: .optional)
        XCTAssertTrue(api.commits.isEmpty)
        XCTAssertTrue(api.pauses.isEmpty)
        XCTAssertTrue(api.sourceChanges.isEmpty)
        XCTAssertTrue(api.classifications.isEmpty)
        gate.release()
        await upload.value

        XCTAssertEqual(uploader.state, .confirmationIndeterminate)
        XCTAssertFalse(model.canCommit)
        XCTAssertFalse(model.canUpload)
        api.confirmError = nil
        await model.reconcileUpload()
        XCTAssertEqual(model.artifactReferences, [.init(artifactID: 90, linkRole: .supporting)])
        XCTAssertTrue(model.canCommit)
        model.disappear()
    }

    func testDisappearDuringConfirmationCannotAttachLateArtifactOrRecreateSavedDraft() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let gate = ActivityTestGate()
        api.beforeConfirm = { await gate.wait() }
        let transport = ActivityFileUploadStub()
        let uploader = ActivityArtifactUploader(api: api, transport: transport)
        let store = InMemoryActivityDraftStore()
        let model = ActivityWorkspaceModel(activityID: 41, api: api, drafts: store,
                                           timerJournal: InMemoryActivityTimerJournal())
        model.connect(uploader: uploader)
        await model.open()
        model.updateDraft(model.draft.setting("audience", to: "Retain on navigation"))
        let upload = Task { await model.upload(sourceURL: source, artifactClass: .writtenOutput) }
        await fulfillment(of: [gate.entered], timeout: 1)

        model.disappear()
        gate.release()
        await upload.value

        XCTAssertTrue(model.artifactReferences.isEmpty)
        XCTAssertTrue(store.load(activityID: 41)?.artifactReferences.isEmpty == true)
        XCTAssertEqual(store.load(activityID: 41)?.value(for: "audience"), "Retain on navigation")
        XCTAssertEqual(uploader.state, .cancelled)
        XCTAssertTrue(transport.uploadedFiles.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testCancelInterruptsRunningConfirmation() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let started = expectation(description: "Confirmation started")
        let cancelled = expectation(description: "Confirmation cancelled")
        api.beforeConfirm = {
            started.fulfill()
            do { try await Task.sleep(for: .seconds(30)) }
            catch { cancelled.fulfill(); throw error }
        }
        let transport = ActivityFileUploadStub()
        let uploader = ActivityArtifactUploader(api: api, transport: transport)
        let upload = Task {
            try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }
        await fulfillment(of: [started], timeout: 1)
        uploader.cancel()
        await fulfillment(of: [cancelled], timeout: 1)
        _ = await upload.result

        XCTAssertEqual(uploader.state, .cancelled)
        XCTAssertTrue(transport.uploadedFiles.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testSecondUploadCannotReplaceIndeterminateConfirmation() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        api.confirmError = .network
        let transport = ActivityFileUploadStub()
        let uploader = ActivityArtifactUploader(api: api, transport: transport)
        defer {
            uploader.cancel()
            transport.uploadedFiles.forEach { try? FileManager.default.removeItem(at: $0) }
        }
        await XCTAssertThrowsErrorAsync {
            _ = try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }
        let original = try XCTUnwrap(api.confirms.first)
        api.confirmError = nil

        await XCTAssertThrowsErrorAsync {
            _ = try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }

        XCTAssertEqual(uploader.state, .confirmationIndeterminate)
        XCTAssertEqual(api.presigns.count, 1)
        XCTAssertEqual(api.confirms, [original])
        _ = try await uploader.reconcile()
        XCTAssertEqual(api.confirms, [original, original])
    }

    func testExplicitAbandonCleansPendingBytesAndAllowsNewUpload() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        api.confirmError = .network
        let transport = ActivityFileUploadStub()
        let uploader = ActivityArtifactUploader(api: api, transport: transport)
        await XCTAssertThrowsErrorAsync {
            _ = try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }
        let staged = try XCTUnwrap(transport.uploadedFiles.first)

        uploader.cancel()

        XCTAssertFalse(FileManager.default.fileExists(atPath: staged.path))
        XCTAssertEqual(uploader.state, .cancelled)
        api.confirmError = nil
        _ = try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        XCTAssertEqual(uploader.state, .complete)
    }

    func testCancelInterruptsRunningPUTAndCleansStagedBytes() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let transport = ActivityFileUploadStub()
        let started = expectation(description: "PUT started")
        let cancelled = expectation(description: "PUT task cancelled")
        transport.beforeUpload = {
            started.fulfill()
            do { try await Task.sleep(for: .seconds(30)) }
            catch { cancelled.fulfill(); throw error }
        }
        let uploader = ActivityArtifactUploader(api: api, transport: transport)
        let upload = Task {
            try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }
        await fulfillment(of: [started], timeout: 1)

        uploader.cancel()
        await fulfillment(of: [cancelled], timeout: 1)
        // Cleanup even when the regression fails against an unowned upload task.
        upload.cancel()
        _ = await upload.result

        XCTAssertEqual(uploader.state, .cancelled)
        XCTAssertTrue(api.confirms.isEmpty)
        XCTAssertTrue(transport.uploadedFiles.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testCancelledPresignCannotProceedToPUTWhenResponseArrivesLate() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let gate = ActivityTestGate()
        api.beforePresign = { await gate.wait() }
        let transport = ActivityFileUploadStub()
        let uploader = ActivityArtifactUploader(api: api, transport: transport)
        let upload = Task {
            try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }
        await fulfillment(of: [gate.entered], timeout: 1)

        uploader.cancel()
        gate.release()
        let result = await upload.result

        if case .success = result { XCTFail("Cancelled presign must not return an attachable artifact") }
        XCTAssertEqual(uploader.state, .cancelled)
        XCTAssertTrue(transport.uploadedFiles.isEmpty)
        XCTAssertTrue(api.confirms.isEmpty)
    }

    func testCancelledConfirmationCannotReturnLateAttachableArtifact() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let gate = ActivityTestGate()
        api.beforeConfirm = { await gate.wait() }
        let transport = ActivityFileUploadStub()
        let uploader = ActivityArtifactUploader(api: api, transport: transport)
        let upload = Task {
            try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }
        await fulfillment(of: [gate.entered], timeout: 1)

        uploader.cancel()
        gate.release()
        let result = await upload.result

        if case .success = result { XCTFail("Cancelled confirmation must not return an attachable artifact") }
        XCTAssertEqual(uploader.state, .cancelled)
        XCTAssertTrue(transport.uploadedFiles.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testCancelledParentNeverStartsStagingOrNetwork() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let uploader = ActivityArtifactUploader(api: api, transport: ActivityFileUploadStub())
        let gate = ActivityTestGate()
        let upload = Task {
            await gate.wait()
            return try await uploader.upload(sourceURL: source, activityID: 41, expectedVersion: 3, artifactClass: .writtenOutput)
        }
        await fulfillment(of: [gate.entered], timeout: 1)
        upload.cancel()
        gate.release()
        let result = await upload.result

        if case .success = result { XCTFail("Cancelled task must not upload") }
        XCTAssertTrue(api.presigns.isEmpty)
        XCTAssertTrue(api.confirms.isEmpty)
        XCTAssertEqual(uploader.state, .cancelled)
    }

    func testStagingChecksCancellationBeforeCopying() async throws {
        let source = try temporaryFile(contents: Data("hello".utf8))
        defer { try? FileManager.default.removeItem(at: source) }
        let gate = ActivityTestGate()
        let task = Task {
            await gate.wait()
            return try ActivityStagedFileStore().stage(sourceURL: source)
        }
        await fulfillment(of: [gate.entered], timeout: 1)
        task.cancel()
        gate.release()

        switch await task.result {
        case let .success(staged):
            ActivityStagedFileStore().remove(staged)
            XCTFail("Cancelled staging must fail before copying")
        case let .failure(error):
            XCTAssertTrue(error is CancellationError || error as? ActivityAPIError == .cancelled)
        }
    }

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

    private func temporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        return directory
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
    var beforeUpload: (() async throws -> Void)?
    private(set) var uploadedFiles: [URL] = []
    private(set) var uploadedByteCounts: [Int] = []

    init(error: Error? = nil) {
        self.error = error
    }

    func upload(fileURL: URL, to url: URL, headers: [String: String]) async throws {
        uploadedFiles.append(fileURL)
        uploadedByteCounts.append((try? FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? Int) ?? 0)
        try await beforeUpload?()
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
