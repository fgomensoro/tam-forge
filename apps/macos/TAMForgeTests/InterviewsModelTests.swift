import Foundation
import XCTest

@MainActor
final class InterviewsModelTests: XCTestCase {
    func testTheTimelineDecodesScoresTrendsAndRecurringGaps() async throws {
        let api = FakeInterviewAPI(records: [record(id: 1, company: "Acme")])
        api.timelineJSON = """
        {"items": [
           {"interview_id": 1, "company": "Acme", "role": "TAM", "stage": "screen", "starts_at": "2026-09-01T17:00:00Z",
            "status": "completed", "has_debrief": true, "hiring_progression": "Advanced.",
            "dimensions": [{"slug": "answer_clarity", "score": "2.5"}, {"slug": "technical_examples", "score": "3"}],
            "skills_affected": [{"skill_slug": "business_value_framing", "direction": "flat"}],
            "gaps": [{"statement": "No impact stated.", "skill_slug": "business_value_framing"}]},
           {"interview_id": 2, "company": "Beta", "role": "TAM", "stage": "panel", "starts_at": "2026-09-08T17:00:00Z",
            "status": "completed", "has_debrief": false, "hiring_progression": null, "dimensions": [], "skills_affected": [], "gaps": []}],
         "debriefed": 1,
         "dimension_trends": [{"slug": "answer_clarity", "name": "Answer clarity and structure",
            "scores": [{"slug": "1", "score": "2.5"}], "latest": "2.5", "delta_from_first": null}],
         "recurring_gaps": [{"skill_slug": "business_value_framing", "interview_count": 2, "statements": ["No impact stated."]}]}
        """
        let model = InterviewsModel(api: api)
        await model.load()
        XCTAssertEqual(api.calls, ["list", "timeline"])
        XCTAssertEqual(model.timeline.debriefed, 1)
        XCTAssertEqual(model.timeline.items[0].score("answer_clarity"), Decimal(string: "2.5"))
        XCTAssertNil(model.timeline.items[1].hiringProgression)
        XCTAssertEqual(model.timelineColumns.map(\.slug), ["answer_clarity"])
        XCTAssertNil(model.timelineColumns[0].deltaFromFirst)
        XCTAssertEqual(model.timeline.recurringGaps.first?.interviewCount, 2)
    }

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

    var timelineJSON = """
    {"items": [], "debriefed": 0, "dimension_trends": [], "recurring_gaps": []}
    """

    func list() async throws -> [InterviewRecord] {
        calls.append("list")
        if let failure { throw failure }
        return records
    }

    func timeline() async throws -> InterviewTimeline {
        calls.append("timeline")
        if let failure { throw failure }
        return try NativeJSONCodec.decode(InterviewTimeline.self, from: Data(timelineJSON.utf8))
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
