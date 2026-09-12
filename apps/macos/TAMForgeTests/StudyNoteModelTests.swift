import Foundation
import XCTest

@MainActor
final class StudyNoteModelTests: XCTestCase {
    func testOpeningWithoutANoteIsAnEmptyFormNotAnError() async {
        let api = FakeStudyNoteAPI(note: nil)
        let model = StudyNoteModel(activityID: 41, api: api)

        await model.open()

        XCTAssertTrue(model.isOpened)
        XCTAssertNil(model.note)
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(api.calls, ["note:41"])
        XCTAssertFalse(model.canSave)
        XCTAssertFalse(model.canApprove)
    }

    func testACoachDraftFillsTheFormAndSaveSendsTheEditedContent() async {
        let api = FakeStudyNoteAPI(note: nil)
        let model = StudyNoteModel(activityID: 41, api: api)
        await model.open()
        api.note = note(status: "draft")

        await model.draft()

        XCTAssertEqual(model.title, "Webhooks: delivery and retries")
        XCTAssertEqual(model.flashcardsText, "What does a 200 confirm? :: Durable acceptance.")
        XCTAssertEqual(model.misconceptionsText, "A 200 means the event was processed.")

        model.title = "Webhooks, reviewed"
        model.flashcardsText = "What does a 200 confirm? :: Durable acceptance.\nbroken line\nQ2? :: A2"
        XCTAssertTrue(model.canSave)
        await model.save()

        XCTAssertEqual(api.calls.last, "save:41")
        XCTAssertEqual(api.savedContent?.title, "Webhooks, reviewed")
        XCTAssertEqual(api.savedContent?.flashcards.count, 2)
        XCTAssertEqual(api.savedContent?.validatedQueries, [NoteQueryItem(query: "SELECT 1;", result: "1")])
    }

    func testApprovalRequiresASavedNoteThatMatchesTheForm() async {
        let api = FakeStudyNoteAPI(note: note(status: "draft"))
        let model = StudyNoteModel(activityID: 41, api: api)
        await model.open()
        XCTAssertTrue(model.canApprove)

        model.rule = "edited but unsaved"
        XCTAssertFalse(model.canApprove)
        await model.approve()
        XCTAssertFalse(api.calls.contains("approve:41"))

        await model.save()
        api.note = note(status: "approved")
        XCTAssertTrue(model.canApprove)
        await model.approve()

        XCTAssertEqual(api.calls.last, "approve:41")
        XCTAssertTrue(model.isApproved)
        XCTAssertFalse(model.canSave)
    }

    func testProblemsBecomeMessagesAndTheFormIsKept() async {
        let api = FakeStudyNoteAPI(note: note(status: "draft"))
        let model = StudyNoteModel(activityID: 41, api: api)
        await model.open()
        api.failure = .conflict
        model.rule = "changed"

        await model.save()

        XCTAssertEqual(model.errorMessage, StudyNoteAPIError.conflict.message)
        XCTAssertEqual(model.rule, "changed")
    }

    func testTheLiveClientDecodesTheServerShapeAndTranslatesProblems() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data("""
        {"id": 5, "activity_id": 41, "stable_id": "p1-w01-d01-roadmap", "local_date": "2026-09-12",
         "status": "approved", "drafted_by": "coach", "assistance": "coached",
         "assessment_status": "self_review_complete", "title": "Webhooks", "rule": "r",
         "explanation": "e", "example": "x", "misconceptions": [], "validated_queries": [],
         "sources": [], "flashcards": [{"question": "Q?", "answer": "A"}], "artifact_id": 9,
         "content_sha256": "ab", "updated_at": "2026-09-12T10:00:00Z", "approved_at": "2026-09-12T10:00:00Z"}
        """.utf8)))
        let api = LiveStudyNoteAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!, session: fixture.session()
        ))

        let note = try await api.note(activityID: 41)

        XCTAssertEqual(note.artifactID, 9)
        XCTAssertTrue(note.isApproved)
        XCTAssertEqual(fixture.requests.first?.url?.path, "/api/v1/activities/41/note")
        XCTAssertEqual(LiveStudyNoteAPI.translate(.problem(problem(status: 404))), .notFound)
        XCTAssertEqual(LiveStudyNoteAPI.translate(.problem(problem(status: 409))), .conflict)
        XCTAssertEqual(LiveStudyNoteAPI.translate(.problem(problem(status: 503))), .unavailable)
        XCTAssertEqual(LiveStudyNoteAPI.translate(.decodingResponse), .invalidResponse)
    }

    private func problem(status: Int) -> APIProblem {
        APIProblem(type: nil, title: nil, status: status, detail: nil, instance: nil, code: nil)
    }

    private func note(status: String) -> StudyNote {
        StudyNote(
            id: 5, activityID: 41, stableID: "p1-w01-d01-roadmap", localDate: "2026-09-12",
            status: status, draftedBy: "coach", assistance: "coached",
            assessmentStatus: "output_committed",
            title: "Webhooks: delivery and retries",
            rule: "A 200 confirms durable acceptance, not processing.",
            explanation: "The provider retries until it sees a 2xx.",
            example: "Stripe retries with backoff.",
            misconceptions: ["A 200 means the event was processed."],
            validatedQueries: [NoteQueryItem(query: "SELECT 1;", result: "1")],
            sources: ["docs/webhooks.md"],
            flashcards: [NoteFlashcardItem(question: "What does a 200 confirm?", answer: "Durable acceptance.")],
            artifactID: status == "approved" ? 9 : nil,
            contentSHA256: status == "approved" ? "ab" : nil,
            updatedAt: Date(timeIntervalSince1970: 0),
            approvedAt: status == "approved" ? Date(timeIntervalSince1970: 0) : nil
        )
    }
}

@MainActor
private final class FakeStudyNoteAPI: StudyNoteAPI {
    var note: StudyNote?
    var failure: StudyNoteAPIError?
    private(set) var calls: [String] = []
    private(set) var savedContent: StudyNoteContent?

    init(note: StudyNote?) {
        self.note = note
    }

    func note(activityID: Int) async throws -> StudyNote {
        calls.append("note:\(activityID)")
        if let failure { throw failure }
        guard let note else { throw StudyNoteAPIError.notFound }
        return note
    }

    func draft(activityID: Int) async throws -> StudyNote {
        calls.append("draft:\(activityID)")
        if let failure { throw failure }
        guard let note else { throw StudyNoteAPIError.conflict }
        return note
    }

    func save(activityID: Int, content: StudyNoteContent) async throws -> StudyNote {
        calls.append("save:\(activityID)")
        if let failure { throw failure }
        savedContent = content
        let base = note ?? StudyNote(
            id: 6, activityID: activityID, stableID: "s", localDate: "2026-09-12", status: "draft",
            draftedBy: "learner", assistance: "independent", assessmentStatus: "ready",
            title: "", rule: "", explanation: "", example: "", misconceptions: [],
            validatedQueries: [], sources: [], flashcards: [], artifactID: nil, contentSHA256: nil,
            updatedAt: Date(timeIntervalSince1970: 0), approvedAt: nil
        )
        let saved = StudyNote(
            id: base.id, activityID: base.activityID, stableID: base.stableID, localDate: base.localDate,
            status: "draft", draftedBy: base.draftedBy, assistance: base.assistance,
            assessmentStatus: base.assessmentStatus, title: content.title, rule: content.rule,
            explanation: content.explanation, example: content.example,
            misconceptions: content.misconceptions, validatedQueries: content.validatedQueries,
            sources: content.sources, flashcards: content.flashcards, artifactID: nil,
            contentSHA256: nil, updatedAt: base.updatedAt, approvedAt: nil
        )
        note = saved
        return saved
    }

    func approve(activityID: Int) async throws -> StudyNote {
        calls.append("approve:\(activityID)")
        if let failure { throw failure }
        guard let note else { throw StudyNoteAPIError.notFound }
        return note
    }
}
