import Foundation
import XCTest

@MainActor
final class InterviewsModelTests: XCTestCase {
    func testImportingTheAnswerBankSendsTheDocumentAndListsItsEntries() async throws {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)

        await model.importReference(kind: .answerBank, title: " answer-bank ", markdown: "\n## Q1\nBecause.\n")
        XCTAssertEqual(api.calls, ["import:answer_bank:answer-bank:14", "references"])
        XCTAssertEqual(model.referenceOutcome?.created, 1)
        XCTAssertEqual(model.references(of: .answerBank).map(\.heading), ["Q1. Why are you leaving?"])
        XCTAssertTrue(model.references(of: .storyCatalog).isEmpty)
        XCTAssertNil(model.errorMessage)

        // The same document again: nothing new, and the list does not grow.
        await model.importReference(kind: .answerBank, title: "", markdown: "## Q1\nBecause.")
        XCTAssertEqual(api.calls.last, "references")
        XCTAssertEqual(api.calls[2], "import:answer_bank:Answer bank:14")
        XCTAssertEqual(model.referenceOutcome?.existing, 1)
        XCTAssertEqual(model.references.count, 1)
    }

    func testAPracticeAnswerIsRetriedUntilItsRecordingAndItsTranscriptReachTheServer() async {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)
        let entry = ReferenceEntry(
            id: 5, kind: .answerBank, documentTitle: "bank", heading: "Q1. Why?", body: "Because.",
            readinessLabel: "", readinessVerified: false
        )
        let answer = PracticeAnswer(question: PracticeQuestion(entry: entry, prompt: "Why?"), recordingID: UUID())

        // Still uploading: the server does not know the recording, so the answer is kept.
        await model.submitPracticeAnswer(answer)
        XCTAssertEqual(model.unsentPracticeAnswers, [answer])
        XCTAssertTrue(model.practiceReviews.isEmpty)
        XCTAssertNotNil(model.errorMessage)

        // Uploaded, not transcribed yet: stored and waiting.
        api.uploadedRecordings = [answer.recordingID]
        await model.refreshPracticeReviews()
        XCTAssertTrue(model.unsentPracticeAnswers.isEmpty)
        XCTAssertEqual(model.practiceReviews.map(\.status), ["awaiting_transcript"])
        XCTAssertEqual(model.practiceReviews.first?.referenceMaterialID, 5)
        XCTAssertNil(model.errorMessage)

        // The transcript arrived: the refresh nudges the waiting answer and it queues.
        api.transcribedRecordings = [answer.recordingID]
        await model.refreshPracticeReviews()
        XCTAssertEqual(model.practiceReviews.map(\.status), ["queued"])
        XCTAssertEqual(model.practiceReviews.first?.statusLabel, "Review queued")
    }

    func testAPracticeReviewDecodesScoresSentAsStrings() throws {
        let json = """
        {"id": 4, "question": "Why?", "recording_id": "10F3D9DE-B6DD-48A4-8F01-BD570E17DE22",
         "reference_material_id": null, "status": "ready", "failure_category": null, "model": "claude-fable-5-1",
         "dimensions": [{"slug": "answer_clarity", "name": "Answer clarity and structure", "score": "3.0",
                         "evidence": "I hit the ceiling", "note": "Direct."}],
         "strengths": ["Opens with the number."],
         "fixes": [{"heard": "at scale", "say_instead": "at real scale", "why": "Anchor."}],
         "reference_coverage": "", "readiness": "drilling",
         "created_at": "2026-09-18T00:00:00Z", "reviewed_at": "2026-09-18T00:05:00Z"}
        """
        let review = try NativeJSONCodec.decode(PracticeAnswerReview.self, from: Data(json.utf8))
        XCTAssertEqual(review.dimensions.first?.score, Decimal(string: "3.0"))
        XCTAssertEqual(review.fixes.first?.sayInstead, "at real scale")
        XCTAssertEqual(review.statusLabel, "Reviewed · drilling")
        XCTAssertNil(review.referenceMaterialID)
    }

    func testAnEmptyReferenceDocumentIsRefusedBeforeTheNetwork() async {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)

        await model.importReference(kind: .storyCatalog, title: "stories", markdown: "  \n ")
        XCTAssertTrue(api.calls.isEmpty)
        XCTAssertEqual(model.errorMessage, "The document is empty or larger than the server accepts.")
    }

    func testAFailedReferenceImportKeepsTheListAndShowsTheError() async {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)
        await model.importReference(kind: .answerBank, title: "bank", markdown: "## Q1\nBecause.")
        api.failure = .network

        await model.importReference(kind: .answerBank, title: "bank", markdown: "## Q2\nNew.")
        XCTAssertEqual(model.references.count, 1)
        XCTAssertNil(model.referenceOutcome)
        XCTAssertEqual(model.errorMessage, InterviewAPIError.network.message)
    }

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
        XCTAssertEqual(api.calls, ["list", "timeline", "references", "practice"])
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

    func testAFollowUpAnswerIsSubmittedWithItsQuestionAndItsParentRecording() async {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)
        let entry = ReferenceEntry(
            id: 5, kind: .answerBank, documentTitle: "bank", heading: "Q1. Why?", body: "Because.",
            readinessLabel: "", readinessVerified: false
        )
        let question = PracticeQuestion(entry: entry, prompt: "Why?")
        let first = PracticeAnswer(question: question, recordingID: UUID())
        let second = PracticeAnswer(
            question: question, recordingID: UUID(),
            followUpQuestion: "What exactly was the ceiling?", parentRecordingID: first.recordingID
        )
        api.uploadedRecordings = [first.recordingID, second.recordingID]

        await model.submitPracticeAnswer(first)
        await model.submitPracticeAnswer(second)

        XCTAssertTrue(model.unsentPracticeAnswers.isEmpty)
        XCTAssertEqual(api.submissions.first, .init(recordingID: first.recordingID, followUpQuestion: nil, parentRecordingID: nil))
        XCTAssertTrue(api.submissions.contains(.init(
            recordingID: second.recordingID, followUpQuestion: "What exactly was the ceiling?",
            parentRecordingID: first.recordingID
        )))
    }

    func testTheFollowUpRequestGoesThroughTheAPIAndAnUnavailableRoleThrows() async throws {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)
        let provider: any PracticeFollowUpProviding = model

        let asked = try await provider.followUp(
            question: "Why?", referenceAnswer: "Because.", transcript: "I hit the ceiling there.",
            priorFollowUps: ["Why now?"]
        )
        XCTAssertEqual(asked, "What exactly was the ceiling?")
        XCTAssertEqual(api.calls.last, "followUp:Why?:1")

        api.failure = .unavailable
        do {
            _ = try await provider.followUp(question: "Why?", referenceAnswer: "", transcript: "x", priorFollowUps: [])
            XCTFail("an unavailable role must throw so the practice moves on")
        } catch {
            XCTAssertEqual(error as? InterviewAPIError, .unavailable)
        }
        XCTAssertNil(model.errorMessage)  // a missing follow-up is not an error on the screen
    }

    func testAReviewOfAFollowUpAnswerDecodesItsQuestionAndOldPayloadsStillDecode() throws {
        let json = """
        {"id": 5, "question": "Why?", "recording_id": "10F3D9DE-B6DD-48A4-8F01-BD570E17DE22",
         "reference_material_id": null, "follow_up_of": 4, "follow_up_question": "What was the ceiling?",
         "status": "ready", "failure_category": null, "model": "claude-fable-5-1",
         "dimensions": [{"slug": "follow_up_handling", "name": "Follow-up handling: answers what was asked and adds to the first answer",
                         "score": "3.0", "evidence": "renewed for two years", "note": "Answers what was asked."}],
         "strengths": [], "fixes": [], "reference_coverage": "", "readiness": "drilling",
         "created_at": "2026-09-18T00:00:00Z", "reviewed_at": "2026-09-18T00:05:00Z"}
        """
        let review = try NativeJSONCodec.decode(PracticeAnswerReview.self, from: Data(json.utf8))
        XCTAssertEqual(review.followUpQuestion, "What was the ceiling?")
        XCTAssertEqual(review.dimensions.first?.slug, "follow_up_handling")
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

    var practiceStore: [PracticeAnswerReview] = []
    var uploadedRecordings: Set<UUID> = []
    var transcribedRecordings: Set<UUID> = []

    struct Submission: Equatable {
        let recordingID: UUID
        let followUpQuestion: String?
        let parentRecordingID: UUID?
    }

    private(set) var submissions: [Submission] = []
    var followUpReply: String? = "What exactly was the ceiling?"

    func practiceAnswers() async throws -> [PracticeAnswerReview] {
        calls.append("practice")
        if let failure { throw failure }
        return practiceStore
    }

    func submitPracticeAnswer(
        question: String, recordingID: UUID, referenceID: Int?,
        followUpQuestion: String?, parentRecordingID: UUID?
    ) async throws -> PracticeAnswerReview {
        calls.append("submit:\(question)")
        if let failure { throw failure }
        guard uploadedRecordings.contains(recordingID) else { throw InterviewAPIError.notFound }
        submissions.append(Submission(
            recordingID: recordingID, followUpQuestion: followUpQuestion, parentRecordingID: parentRecordingID
        ))
        let status = transcribedRecordings.contains(recordingID) ? "queued" : "awaiting_transcript"
        let review = PracticeAnswerReview(
            id: 1, question: question, recordingID: recordingID, referenceMaterialID: referenceID,
            followUpQuestion: followUpQuestion, status: status,
            failureCategory: nil, dimensions: [], strengths: [], fixes: [], referenceCoverage: "", readiness: nil,
            createdAt: Date(timeIntervalSince1970: 0)
        )
        practiceStore = [review]
        return review
    }

    func practiceFollowUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String? {
        calls.append("followUp:\(question):\(priorFollowUps.count)")
        if let failure { throw failure }
        return followUpReply
    }

    var referenceEntries: [ReferenceEntry] = []

    func references() async throws -> [ReferenceEntry] {
        calls.append("references")
        if let failure { throw failure }
        return referenceEntries
    }

    func importReference(kind: ReferenceKind, title: String, markdown: String) async throws -> ReferenceImportOutcome {
        calls.append("import:\(kind.rawValue):\(title):\(markdown.count)")
        if let failure { throw failure }
        let entry = ReferenceEntry(
            id: referenceEntries.count + 1, kind: kind, documentTitle: title, heading: "Q1. Why are you leaving?",
            body: markdown, readinessLabel: "READY", readinessVerified: false
        )
        let known = referenceEntries.contains { $0.body == markdown && $0.kind == kind }
        if !known { referenceEntries.append(entry) }
        return ReferenceImportOutcome(kind: kind, created: known ? 0 : 1, existing: known ? 1 : 0, entries: [entry])
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
