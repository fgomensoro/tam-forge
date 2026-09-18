import Foundation
import XCTest

@MainActor
final class CardsModelTests: XCTestCase {
    func testDueCardsAreRunOneAtATimeAndGradedAfterReveal() async {
        let api = FakeCardAPI()
        api.due = [
            CardRecord(id: 1, question: "200?", answer: "Accepted.", skillSlug: "api_contracts", dueOn: "2026-09-16"),
            CardRecord(id: 2, question: "Idempotency?", answer: "Same result.", skillSlug: "api_contracts", dueOn: "2026-09-15"),
        ]
        let model = CardsModel(api: api, today: { "2026-09-16" })
        await model.load()
        XCTAssertEqual(model.remaining, 2)
        XCTAssertEqual(model.current?.id, 1)
        XCTAssertFalse(model.canGrade)

        await model.grade(4)
        XCTAssertEqual(api.reviews.count, 0, "a grade before the reveal is ignored")
        model.reveal()
        XCTAssertTrue(model.canGrade)
        await model.grade(4)
        XCTAssertEqual(api.reviews.map(\.cardID), [1])
        XCTAssertEqual(api.reviews.first?.mode, "written")
        XCTAssertNil(api.reviews.first?.recordingID)
        XCTAssertEqual(api.reviews.first?.reviewedOn, "2026-09-16")
        XCTAssertEqual(model.current?.id, 2)
        XCTAssertEqual(model.reviewedCount, 1)
        XCTAssertFalse(model.isRevealed)
        XCTAssertEqual(model.lastOutcome?.intervalAfter, 1)
    }

    func testSpokenModeNeedsARecordingBeforeTheGrade() async {
        let api = FakeCardAPI()
        api.due = [CardRecord(id: 1, question: "q", answer: "a", skillSlug: "tam_english", dueOn: "2026-09-16")]
        let model = CardsModel(api: api, coordinator: nil, today: { "2026-09-16" })
        await model.load()
        model.mode = .spoken
        model.reveal()
        XCTAssertFalse(model.canGrade, "spoken reviews carry their recording")
        XCTAssertFalse(model.canRecord, "no coordinator means no recording")
        await model.grade(5)
        XCTAssertTrue(api.reviews.isEmpty)
    }

    func testCreatingACardDueTodayJoinsTheQueueAndErrorsBecomeMessages() async {
        let api = FakeCardAPI()
        let model = CardsModel(api: api, today: { "2026-09-16" })
        await model.load()
        XCTAssertFalse(model.canCreate)
        model.draft = CardDraft(question: "What is TAM?", answer: "Technical account management.", skillSlug: "tam_general")
        XCTAssertTrue(model.canCreate)
        await model.create()
        XCTAssertEqual(model.current?.question, "What is TAM?")
        XCTAssertEqual(model.draft, .empty())

        api.failure = .unavailable
        await model.importRoadmapVersion(8)
        XCTAssertEqual(model.errorMessage, CardAPIError.unavailable.message)
        api.failure = nil
        await model.importRoadmapVersion(8)
        XCTAssertEqual(model.lastImport?.created, 3)
        XCTAssertNil(model.errorMessage)
    }

    func testPracticeDrawsATopicsCardsWhateverTheirDueDateAndGradesAreRealReviews() async {
        let api = FakeCardAPI()
        let retries = "package:study-notes/2026-09-16 - Retries Backoff and Jitter Study Notes.md"
        let webhooks = "package:study-notes/2026-09-09 - Webhooks Rate Limits and Recovery Study Notes.md"
        api.library = [
            CardRecord(id: 1, question: "q1", answer: "a1", skillSlug: "general", sourceRef: retries, dueOn: "2026-10-01"),
            CardRecord(id: 2, question: "q2", answer: "a2", skillSlug: "general", sourceRef: webhooks, dueOn: "2026-10-02"),
            CardRecord(id: 3, question: "q3", answer: "a3", skillSlug: "tam_english", sourceRef: webhooks, dueOn: "2026-10-03"),
        ]
        let model = CardsModel(api: api, today: { "2026-09-18" }, shuffle: { $0.reversed() })
        await model.load()
        XCTAssertNil(model.current)  // nothing is due, and that no longer stops practice

        await model.loadLibrary()
        XCTAssertEqual(
            model.practiceTopics.map(\.title),
            ["All cards, mixed", "General", "Tam English", "Webhooks Rate Limits and Recovery", "Retries Backoff and Jitter"]
        )
        XCTAssertEqual(model.practiceTopics.map(\.count), [3, 2, 1, 2, 1])

        model.practiceTopicID = "source:\(webhooks)"
        await model.startPractice()
        XCTAssertTrue(model.isPracticing)
        XCTAssertEqual(model.queue.map(\.id), [3, 2])  // the topic only, in the shuffled order

        model.reveal()
        await model.grade(4)
        XCTAssertEqual(api.reviews.map(\.cardID), [3])
        XCTAssertEqual(api.reviews[0].reviewedOn, "2026-09-18")
        XCTAssertEqual(model.remaining, 1)

        await model.stopPractice()
        XCTAssertFalse(model.isPracticing)
        XCTAssertNil(model.current)
    }

    func testPracticeWithNoCardsForTheTopicDoesNothing() async {
        let api = FakeCardAPI()
        let model = CardsModel(api: api, today: { "2026-09-18" })
        await model.loadLibrary()
        XCTAssertTrue(model.practiceTopics.isEmpty)
        XCTAssertFalse(model.canPractice)
        await model.startPractice()
        XCTAssertFalse(model.isPracticing)
    }

    func testANoteTitleDropsThePathTheDateAndTheStudyNotesSuffix() {
        XCTAssertEqual(
            PracticeTopic.sourceTitle("package:study-notes/2026-09-15 - API Design Study Notes.md"), "API Design"
        )
        XCTAssertEqual(PracticeTopic.sourceTitle("answer-bank"), "answer-bank")
        XCTAssertEqual(PracticeTopic.sourceTitle("note:12"), "12")
    }

    func testCardPayloadsDecodeDecimalsSentAsStrings() throws {
        let json = """
        {"card": {"id": 4, "question": "q", "answer": "a", "skill_slug": "s", "source_kind": "coach",
          "source_ref": "coach:1:0", "assistance": "coached", "status": "active", "scheduler_version": "sm2-v1",
          "easiness": "2.36", "interval_days": 6, "repetitions": 2, "due_on": "2026-09-22",
          "created_at": "2026-09-16T12:00:00Z", "updated_at": "2026-09-16T12:00:00Z"},
         "review": {"id": 9, "card_id": 4, "grade": 3, "mode": "spoken", "reviewed_on": "2026-09-16",
          "interval_before": 1, "interval_after": 6, "easiness_after": "2.36", "due_after": "2026-09-22",
          "created_at": "2026-09-16T12:00:00Z"}}
        """
        let outcome = try NativeJSONCodec.decode(CardReviewOutcome.self, from: Data(json.utf8))
        XCTAssertEqual(outcome.card.easiness, Decimal(string: "2.36"))
        XCTAssertEqual(outcome.intervalAfter, 6)
        XCTAssertEqual(outcome.dueAfter, "2026-09-22")
    }
}

@MainActor
private final class FakeCardAPI: CardAPI {
    struct Review: Equatable {
        let cardID: Int
        let grade: Int
        let reviewedOn: String
        let mode: String
        let recordingID: UUID?
    }

    var due: [CardRecord] = []
    var library: [CardRecord] = []
    var failure: CardAPIError?

    func all() async throws -> [CardRecord] {
        if let failure { throw failure }
        return library
    }
    private(set) var reviews: [Review] = []

    func due(on localDate: String) async throws -> [CardRecord] {
        if let failure { throw failure }
        return due
    }

    func create(_ draft: CardDraft) async throws -> CardRecord {
        if let failure { throw failure }
        let record = CardRecord(id: 10, question: draft.question, answer: draft.answer, skillSlug: draft.skillSlug, dueOn: "2026-09-16")
        due.append(record)
        return record
    }

    func review(cardID: Int, grade: Int, reviewedOn: String, mode: String, recordingID: UUID?) async throws -> CardReviewOutcome {
        if let failure { throw failure }
        reviews.append(Review(cardID: cardID, grade: grade, reviewedOn: reviewedOn, mode: mode, recordingID: recordingID))
        let card = (due + library).first { $0.id == cardID }!
        due.removeAll { $0.id == cardID }
        return CardReviewOutcome(card: card, intervalAfter: 1, dueAfter: "2026-09-17")
    }

    func importRoadmapVersion(_ versionID: Int) async throws -> CardImportOutcome {
        if let failure { throw failure }
        return CardImportOutcome(sourceRef: "roadmap-version:\(versionID)", created: 3, existing: 0)
    }
}
