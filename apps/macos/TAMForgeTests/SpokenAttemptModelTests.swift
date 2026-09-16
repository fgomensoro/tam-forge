import Foundation
import XCTest

@MainActor
final class SpokenAttemptModelTests: XCTestCase {
    func testRefreshListsRecordingsAndLoadsAnalysesOnlyForAcceptedTranscripts() async {
        let accepted = UUID()
        let pending = UUID()
        let server = FakeSpokenServer(recordings: [
            RecordingServerStatus(
                recordingID: accepted, audioCreatedOnServer: true, transcriptLineageAccepted: true,
                state: "stored", activityID: 41
            ),
            RecordingServerStatus(
                recordingID: pending, audioCreatedOnServer: true, transcriptLineageAccepted: false,
                state: "stored", activityID: 41
            ),
        ])
        let model = SpokenAttemptModel(activityID: 41, coordinator: RecordingCoordinator(), server: server)

        await model.refresh()

        XCTAssertEqual(model.recordings.count, 2)
        XCTAssertEqual(server.analysisRequests, [accepted])
        XCTAssertEqual(model.analysis(for: model.recordings[0]).turns.first?.text, "hello there")
        XCTAssertEqual(model.analysis(for: model.recordings[1]).status, "not_requested")
        XCTAssertNil(model.errorMessage)
    }

    func testAServerFailureIsAMessageNotACrash() async {
        let server = FakeSpokenServer(recordings: [])
        server.fail = true
        let model = SpokenAttemptModel(activityID: 41, coordinator: RecordingCoordinator(), server: server)

        await model.refresh()

        XCTAssertEqual(model.recordings, [])
        XCTAssertNotNil(model.errorMessage)
    }

    func testTheCreatePayloadCarriesTheActivityIdOnlyWhenPresent() throws {
        let tracks = [RecordingTrackDeclarationPayload(trackID: "t", kind: "microphone", format: .init(channelCount: 1))]
        let linked = try RecordingCanonicalJSON.encode(
            RecordingCreatePayload(recordingID: "r", startedAt: "2026-09-15T10:00:00Z", tracks: tracks, activityID: 41)
        )
        let free = try RecordingCanonicalJSON.encode(
            RecordingCreatePayload(recordingID: "r", startedAt: "2026-09-15T10:00:00Z", tracks: tracks)
        )

        XCTAssertTrue(String(decoding: linked, as: UTF8.self).contains("\"activity_id\":41"))
        XCTAssertFalse(String(decoding: free, as: UTF8.self).contains("activity_id"))
    }

    func testTheActivityLinkSidecarRoundTripsBesideTheSpool() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let recordingID = UUID()
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent(recordingID.uuidString, isDirectory: true),
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }

        XCTAssertNil(RecordingActivityLink.read(recordingID: recordingID, rootURL: root))
        try RecordingActivityLink.write(activityID: 41, recordingID: recordingID, rootURL: root)
        XCTAssertEqual(RecordingActivityLink.read(recordingID: recordingID, rootURL: root), 41)
    }
}

@MainActor
private final class FakeSpokenServer: RecordingServerServicing, @unchecked Sendable {
    var recordings: [RecordingServerStatus]
    var fail = false
    private(set) var analysisRequests: [UUID] = []

    init(recordings: [RecordingServerStatus]) {
        self.recordings = recordings
    }

    func create(_ command: RecordingCreatePayload, idempotencyKey: String) async throws {}
    func upload(_ part: RecordingPreparedPart) async throws {}
    func seal(_ command: RecordingSealPayload, idempotencyKey: String) async throws -> RecordingServerStatus {
        throw RecordingUploadError.invalidResponse
    }
    func submitTranscript(_ command: TranscriptSubmitPayload, idempotencyKey: String) async throws -> RecordingServerStatus {
        throw RecordingUploadError.invalidResponse
    }
    func status(recordingID: UUID) async throws -> RecordingServerStatus {
        throw RecordingUploadError.invalidResponse
    }
    func recordings(activityID: Int) async throws -> [RecordingServerStatus] {
        if fail { throw RecordingUploadError.offline }
        return recordings
    }
    func analysis(recordingID: UUID) async throws -> RecordingAnalysis {
        analysisRequests.append(recordingID)
        return RecordingAnalysis(
            status: "published", failureCategory: nil, analysisVersion: "speech-analysis-v1",
            turns: [RecordingTurn(speaker: "learner", startMS: 1_200, endMS: 2_100, text: "hello there")]
        )
    }
}
