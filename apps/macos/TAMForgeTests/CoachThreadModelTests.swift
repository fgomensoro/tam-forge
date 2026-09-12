import Foundation
import XCTest

@MainActor
final class CoachThreadModelTests: XCTestCase {
    func testOpenLoadsTheThreadOnlyWhenAsked() async {
        let api = FakeCoachAPI(thread: thread(allowed: true))
        let model = CoachThreadModel(activityID: 41, api: api)

        XCTAssertFalse(model.isOpened)
        XCTAssertEqual(api.calls, [])

        await model.open()

        XCTAssertTrue(model.isOpened)
        XCTAssertEqual(api.calls, ["thread:41"])
        XCTAssertEqual(model.thread?.nextStep, "Explain the trade-off in one sentence.")
    }

    func testSendTrimsTheDraftAndClearsItAfterTheCoachAnswers() async {
        let api = FakeCoachAPI(thread: thread(allowed: true))
        let model = CoachThreadModel(activityID: 41, api: api)
        await model.open()
        model.draft = "  why is my answer vague?  "

        XCTAssertTrue(model.canSend)
        await model.send()

        XCTAssertEqual(api.calls, ["thread:41", "send:41:why is my answer vague?"])
        XCTAssertEqual(model.draft, "")
    }

    func testSendIsRefusedWhenTheBlockDoesNotAllowCoaching() async {
        let api = FakeCoachAPI(thread: thread(allowed: false))
        let model = CoachThreadModel(activityID: 41, api: api)
        await model.open()
        model.draft = "hello"

        XCTAssertFalse(model.canSend)
        await model.send()

        XCTAssertEqual(api.calls, ["thread:41"])
    }

    func testARefusedBlockRendersAsAStateNotAnError() async {
        let api = FakeCoachAPI(thread: thread(allowed: true), failure: .notAllowed)
        let model = CoachThreadModel(activityID: 41, api: api)

        await model.open()

        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.thread?.coachingAllowed, false)
    }

    func testAnUnavailableCoachKeepsTheThreadAndShowsTheMessage() async {
        let api = FakeCoachAPI(thread: thread(allowed: true))
        let model = CoachThreadModel(activityID: 41, api: api)
        await model.open()
        api.failure = .unavailable
        model.draft = "again"

        await model.send()

        XCTAssertEqual(model.errorMessage, CoachAPIError.unavailable.message)
        XCTAssertEqual(model.draft, "again")
        XCTAssertNotNil(model.thread)
    }

    func testAcceptEvidenceForwardsTheMessageAndIndex() async {
        let api = FakeCoachAPI(thread: thread(allowed: true))
        let model = CoachThreadModel(activityID: 41, api: api)
        await model.open()

        await model.accept(messageID: 7, index: 2)

        XCTAssertEqual(api.calls.last, "evidence:41:7:2")
    }

    func testTheLiveClientDecodesTheServerShapeAndTranslatesProblems() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data("""
        {"activity_id": 41, "thread_id": 3, "coaching_allowed": true, "committed": true,
         "next_step": "Name the failure mode.",
         "messages": [{"id": 7, "speaker": "coach", "text": "Which part felt weakest?",
                       "next_step": "Name the failure mode.",
                       "proposed_evidence": [{"index": 0, "kind": "note", "text": "Weak spot named", "accepted": false}],
                       "created_at": "2026-09-12T10:00:00Z"}]}
        """.utf8)))
        let api = LiveCoachAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!, session: fixture.session()
        ))

        let thread = try await api.thread(activityID: 41)

        XCTAssertEqual(thread.threadID, 3)
        XCTAssertEqual(thread.messages.first?.proposedEvidence.first?.kind, "note")
        XCTAssertEqual(fixture.requests.first?.url?.path, "/api/v1/activities/41/coach")

        XCTAssertEqual(LiveCoachAPI.translate(.problem(problem(status: 403, code: "coaching_not_allowed"))), .notAllowed)
        XCTAssertEqual(LiveCoachAPI.translate(.problem(problem(status: 503, code: "coach_unavailable"))), .unavailable)
        XCTAssertEqual(LiveCoachAPI.translate(.problem(problem(status: 401, code: nil))), .unauthorized)
        XCTAssertEqual(LiveCoachAPI.translate(.decodingResponse), .invalidResponse)
    }

    private func problem(status: Int, code: String?) -> APIProblem {
        APIProblem(type: nil, title: nil, status: status, detail: nil, instance: nil, code: code)
    }

    private func thread(allowed: Bool) -> CoachThread {
        CoachThread(
            activityID: 41, threadID: allowed ? 3 : nil, coachingAllowed: allowed, committed: true,
            nextStep: allowed ? "Explain the trade-off in one sentence." : "",
            messages: []
        )
    }
}

@MainActor
private final class FakeCoachAPI: CoachAPI {
    var thread: CoachThread
    var failure: CoachAPIError?
    private(set) var calls: [String] = []

    init(thread: CoachThread, failure: CoachAPIError? = nil) {
        self.thread = thread
        self.failure = failure
    }

    func thread(activityID: Int) async throws -> CoachThread {
        calls.append("thread:\(activityID)")
        if let failure { throw failure }
        return thread
    }

    func send(activityID: Int, text: String) async throws -> CoachThread {
        calls.append("send:\(activityID):\(text)")
        if let failure { throw failure }
        return thread
    }

    func acceptEvidence(activityID: Int, messageID: Int, index: Int) async throws -> CoachThread {
        calls.append("evidence:\(activityID):\(messageID):\(index)")
        if let failure { throw failure }
        return thread
    }
}
