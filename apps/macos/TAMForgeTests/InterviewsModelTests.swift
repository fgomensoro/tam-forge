import Foundation
import XCTest

@MainActor
final class InterviewsModelTests: XCTestCase {
    func testLoadListsRecordsAndSelectingOneFillsTheDraft() async {
        let api = FakeInterviewAPI(records: [record(id: 1, company: "Acme")])
        let model = InterviewsModel(api: api)

        await model.load()
        XCTAssertEqual(model.interviews.count, 1)
        XCTAssertTrue(model.isCreating)

        model.select(model.interviews[0])
        XCTAssertEqual(model.selectedID, 1)
        XCTAssertEqual(model.draft.company, "Acme")
        XCTAssertFalse(model.isCreating)
    }

    func testCreateThenSaveEditsTheSameRecord() async {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)
        model.draft = InterviewDraft(
            company: "Acme", role: "TAM", stage: "screen", startsAt: Date(timeIntervalSince1970: 100),
            expectedDurationMinutes: 45, status: "scheduled", privacyPermissionCode: "permission_granted"
        )

        XCTAssertTrue(model.canSave)
        await model.save()
        XCTAssertEqual(api.calls, ["create"])
        XCTAssertEqual(model.selectedID, 7)
        XCTAssertEqual(model.interviews.first?.company, "Acme")

        model.draft.stage = "panel"
        await model.save()
        XCTAssertEqual(api.calls, ["create", "update:7"])
        XCTAssertEqual(model.interviews.first?.stage, "panel")
    }

    func testAttachingAndOpeningATranscriptGoThroughTheServer() async {
        let recordingID = UUID()
        let api = FakeInterviewAPI(records: [record(id: 1, company: "Acme")])
        let model = InterviewsModel(api: api)
        await model.load()
        model.select(model.interviews[0])

        await model.attach(recordingID: recordingID)
        XCTAssertEqual(api.calls.last, "attach:1:\(recordingID.uuidString.lowercased())")
        XCTAssertEqual(model.selected?.recordings.first?.recordingID, recordingID)

        await model.openTranscript(recordingID: recordingID)
        XCTAssertEqual(model.analysis(for: model.selected!.recordings[0])?.turns.first?.text, "tell me about retries")
    }

    func testAnInvalidDraftCannotBeSavedAndProblemsBecomeMessages() async {
        let api = FakeInterviewAPI(records: [])
        api.failure = .conflict
        let model = InterviewsModel(api: api)
        XCTAssertFalse(model.canSave)

        await model.load()
        XCTAssertEqual(model.errorMessage, InterviewAPIError.conflict.message)
    }

    private func record(id: Int, company: String, recordings: [InterviewRecordingSummary] = []) -> InterviewRecord {
        InterviewRecord(
            id: id, company: company, role: "TAM", stage: "screen", startsAt: Date(timeIntervalSince1970: 100),
            expectedDurationMinutes: 45, status: "scheduled", privacyPermissionCode: "permission_granted",
            recordings: recordings, createdAt: Date(timeIntervalSince1970: 0), updatedAt: Date(timeIntervalSince1970: 0)
        )
    }
}

@MainActor
private final class FakeInterviewAPI: InterviewAPI {
    var records: [InterviewRecord]
    var failure: InterviewAPIError?
    private(set) var calls: [String] = []

    init(records: [InterviewRecord]) {
        self.records = records
    }

    func list() async throws -> [InterviewRecord] {
        calls.append("list")
        if let failure { throw failure }
        return records
    }

    func create(_ draft: InterviewDraft) async throws -> InterviewRecord {
        calls.append("create")
        if let failure { throw failure }
        let record = make(id: 7, draft: draft, recordings: [])
        records.insert(record, at: 0)
        return record
    }

    func update(id: Int, draft: InterviewDraft) async throws -> InterviewRecord {
        calls.append("update:\(id)")
        if let failure { throw failure }
        let existing = records.first { $0.id == id }
        let record = make(id: id, draft: draft, recordings: existing?.recordings ?? [])
        records = records.map { $0.id == id ? record : $0 }
        return record
    }

    func attach(recordingID: UUID, to id: Int) async throws -> InterviewRecord {
        calls.append("attach:\(id):\(recordingID.uuidString.lowercased())")
        if let failure { throw failure }
        let existing = records.first { $0.id == id }!
        let record = make(
            id: id, draft: InterviewDraft(record: existing),
            recordings: existing.recordings + [InterviewRecordingSummary(
                recordingID: recordingID, state: "stored", startedAt: nil, transcriptLineageAccepted: true
            )]
        )
        records = records.map { $0.id == id ? record : $0 }
        return record
    }

    func analysis(recordingID: UUID) async throws -> RecordingAnalysis {
        calls.append("analysis")
        return RecordingAnalysis(
            status: "published", failureCategory: nil, analysisVersion: "speech-analysis-v1",
            turns: [RecordingTurn(speaker: "other", startMS: 0, endMS: 700, text: "tell me about retries")]
        )
    }

    private func make(id: Int, draft: InterviewDraft, recordings: [InterviewRecordingSummary]) -> InterviewRecord {
        InterviewRecord(
            id: id, company: draft.company, role: draft.role, stage: draft.stage, startsAt: draft.startsAt,
            expectedDurationMinutes: draft.expectedDurationMinutes, status: draft.status,
            privacyPermissionCode: draft.privacyPermissionCode, recordings: recordings,
            createdAt: Date(timeIntervalSince1970: 0), updatedAt: Date(timeIntervalSince1970: 0)
        )
    }
}
