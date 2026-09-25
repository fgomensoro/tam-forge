import Combine
import Foundation
import XCTest

@MainActor
final class CoachThreadModelTests: XCTestCase {
    func testTodayOpensTheGeneralThreadAndSendsTheScreenWithTheDayPlan() async {
        let api = FakeCoachAPI()
        let context = CoachContext()
        context.todaySummary = "- Recall the trade-off (Technical Learning, ready, 30 min)"
        let model = CoachThreadModel(api: api, context: context)

        XCTAssertEqual(api.calls, [])
        await model.toggle()

        XCTAssertTrue(model.isPresented)
        XCTAssertEqual(api.calls, ["general"])
        XCTAssertNil(model.activityID)

        model.draft = "  what should I start with?  "
        XCTAssertTrue(model.canSend)
        await model.send()

        XCTAssertEqual(api.calls, ["general", "sendGeneral:what should I start with?"])
        XCTAssertEqual(api.lastScreenContext, CoachScreenContext(screen: "Today", summary: context.todaySummary))
        XCTAssertEqual(model.draft, "")
        XCTAssertEqual(model.messages.map(\.text), ["reply"])
    }

    func testOtherScreensSendTheirNameAndNoSummary() async {
        let api = FakeCoachAPI()
        let context = CoachContext()
        context.route = .cards
        context.todaySummary = "- the day's plan"
        let model = CoachThreadModel(api: api, context: context)
        model.draft = "how do cards work?"

        await model.send()

        XCTAssertEqual(api.lastScreenContext, CoachScreenContext(screen: "Cards", summary: ""))
    }

    func testAnActivitySendCarriesTheStepAndTheDraftFields() async {
        let api = FakeCoachAPI()
        let context = activityContext()
        context.draftFields = { [CoachDraftField(name: "attempt", value: "Queues decouple producers.")] }
        let model = CoachThreadModel(api: api, context: context)
        model.draft = "is this enough?"

        await model.send()

        XCTAssertEqual(model.activityID, 19)
        XCTAssertEqual(api.calls, ["send:19:is this enough?"])
        XCTAssertEqual(
            api.lastWorkingContext,
            CoachWorkingContext(step: "Do it", fields: [CoachDraftField(name: "attempt", value: "Queues decouple producers.")])
        )
        XCTAssertEqual(model.activityThread?.activityID, 19)
        XCTAssertEqual(model.draft, "")
    }

    func testBlankDraftFieldsAreNotSent() async {
        let api = FakeCoachAPI()
        let context = activityContext()
        context.draftFields = {
            [
                CoachDraftField(name: "attempt", value: "Queues decouple producers."),
                CoachDraftField(name: "empty", value: ""),
                CoachDraftField(name: "spaces", value: "  \n\t "),
            ]
        }
        let model = CoachThreadModel(api: api, context: context)
        model.draft = "is this enough?"

        await model.send()

        XCTAssertEqual(api.lastWorkingContext?.fields.map(\.name), ["attempt"])
    }

    func testTheWorkingContextIsClampedToTheServerLimits() async {
        let api = FakeCoachAPI()
        let context = CoachContext()
        context.route = .activity(19)
        context.activity = ActivityStanding(
            activityID: 19, block: "SQL", stepLabel: String(repeating: "s", count: 300), stepNumber: 1, stepCount: 6
        )
        context.draftFields = {
            (0..<25).map { CoachDraftField(name: String(repeating: "n", count: 70) + "\($0)", value: String(repeating: "v", count: 5_000)) }
        }
        let model = CoachThreadModel(api: api, context: context)
        model.draft = "help"

        await model.send()

        guard let sent = api.lastWorkingContext else { return XCTFail("no context sent") }
        XCTAssertEqual(sent.step.count, 200)
        XCTAssertLessThanOrEqual(sent.fields.count, 20)
        XCTAssertTrue(sent.fields.allSatisfy { $0.name.count <= 64 && $0.value.count <= 4_000 })
        let total = sent.step.count + sent.fields.reduce(0) { $0 + $1.name.count + $1.value.count }
        XCTAssertLessThanOrEqual(total, 12_000)
        XCTAssertGreaterThan(total, 11_000, "the budget is used, not thrown away")
    }

    func testTitleNamesTheActivityStepAndBlockOrTheScreen() {
        let context = activityContext()
        let model = CoachThreadModel(api: FakeCoachAPI(), context: context)

        XCTAssertEqual(model.title, "Activity 19 · Step 2 of 5 · Technical Learning")

        context.activity = ActivityStanding(activityID: 19, block: "Technical Learning", stepLabel: nil, stepNumber: nil, stepCount: 5)
        XCTAssertEqual(model.title, "Activity 19 · Technical Learning")

        context.route = .activity(20)
        XCTAssertEqual(model.title, "Activity 20", "a standing for another activity is not this one's")

        let screens: [(ShellRoute, String)] = [
            (.today, "Today"), (.roadmaps, "Roadmaps"), (.recording, "Recording"), (.interviews, "Interviews"),
            (.classes, "English classes"), (.cards, "Cards"), (.progress, "Progress"), (.evidence(activityID: 4), "Evidence"),
        ]
        for (route, name) in screens {
            context.route = route
            XCTAssertEqual(model.title, name)
        }
    }

    func testARouteChangeWhilePresentedLoadsTheNewTarget() async {
        let api = FakeCoachAPI()
        let context = activityContext()
        let model = CoachThreadModel(api: api, context: context)
        await model.toggle()
        XCTAssertEqual(api.calls, ["thread:19"])

        context.route = .today
        await model.routeChanged()

        XCTAssertEqual(api.calls, ["thread:19", "general"])
        XCTAssertNil(model.activityThread)
        XCTAssertNotNil(model.generalThread)
    }

    func testARouteChangeWhileClosedDropsTheActivityThreadAndLoadsNothing() async {
        let api = FakeCoachAPI()
        let context = activityContext()
        let model = CoachThreadModel(api: api, context: context)
        await model.toggle()
        await model.toggle()
        XCTAssertEqual(model.activityThread?.activityID, 19)

        context.route = .activity(20)
        await model.routeChanged()

        XCTAssertFalse(model.isPresented)
        XCTAssertNil(model.activityThread)
        XCTAssertEqual(api.calls, ["thread:19"])
    }

    func testAThreadForAnotherActivityIsNeverShown() async {
        let api = FakeCoachAPI()
        let context = activityContext()
        let model = CoachThreadModel(api: api, context: context)
        await model.reload()
        XCTAssertEqual(model.messages.map(\.text), ["thread 19"])

        // The shell moves the route before it calls routeChanged().
        context.route = .activity(20)

        XCTAssertEqual(model.activityThread?.activityID, 19)
        XCTAssertNil(model.shownActivityThread)
        XCTAssertEqual(model.messages, [])
    }

    func testARouteChangeDuringASendKeepsTheCoachBusyUntilTheSendReturns() async {
        let api = FakeCoachAPI()
        let gate = ActivityTestGate()
        api.sendGate = gate
        let context = activityContext()
        let model = CoachThreadModel(api: api, context: context)
        await model.toggle()
        model.draft = "hint?"

        let sending = Task { await model.send() }
        await fulfillment(of: [gate.entered], timeout: 1)
        context.route = .today
        await model.routeChanged()

        XCTAssertEqual(api.calls, ["thread:19", "send:19:hint?", "general"])
        XCTAssertTrue(model.isBusy, "the send is still in flight")
        XCTAssertFalse(model.canSend)
        await model.send()
        XCTAssertEqual(api.calls.filter { $0.hasPrefix("send") }, ["send:19:hint?"], "no second send")

        gate.release()
        await sending.value
        XCTAssertFalse(model.isBusy)
    }

    func testClosingTheCoachLoadsNothing() async {
        let api = FakeCoachAPI()
        let model = CoachThreadModel(api: api, context: CoachContext())
        await model.toggle()
        await model.toggle()

        XCTAssertFalse(model.isPresented)
        XCTAssertEqual(api.calls, ["general"])
    }

    func testAThreadForAnActivityTheOwnerAlreadyLeftIsDropped() async {
        let api = FakeCoachAPI()
        let context = activityContext()
        api.duringCall = { context.route = .activity(20) }
        let model = CoachThreadModel(api: api, context: context)

        await model.reload()

        XCTAssertNil(model.activityThread)
    }

    func testAcceptForwardsOnTheActivityAndDoesNothingElsewhere() async {
        let api = FakeCoachAPI()
        let context = activityContext()
        let model = CoachThreadModel(api: api, context: context)

        await model.accept(messageID: 7, index: 2)
        context.route = .today
        await model.accept(messageID: 7, index: 2)

        XCTAssertEqual(api.calls, ["evidence:19:7:2"])
    }

    func testAnUnavailableCoachShowsTheMessageAndKeepsTheDraft() async {
        let api = FakeCoachAPI()
        api.failure = .unavailable
        let model = CoachThreadModel(api: api, context: CoachContext())
        model.draft = "again"

        await model.send()

        XCTAssertEqual(model.errorMessage, CoachAPIError.unavailable.message)
        XCTAssertEqual(model.draft, "again")
        XCTAssertFalse(model.isBusy)

        model.dismissError()
        XCTAssertNil(model.errorMessage)
    }

    func testABlankDraftCannotBeSent() async {
        let api = FakeCoachAPI()
        let model = CoachThreadModel(api: api, context: CoachContext())
        model.draft = "   \n"

        XCTAssertFalse(model.canSend)
        await model.send()

        XCTAssertEqual(api.calls, [])
    }

    func testAStandingChangeRepublishesTheModel() {
        let context = activityContext()
        let model = CoachThreadModel(api: FakeCoachAPI(), context: context)
        var changes = 0
        let subscription = model.objectWillChange.sink { changes += 1 }

        context.activity = ActivityStanding(activityID: 19, block: "Technical Learning", stepLabel: "Commit", stepNumber: 4, stepCount: 5)

        XCTAssertGreaterThan(changes, 0)
        subscription.cancel()
    }

    func testTodaySummaryListsTheTasksInRoadmapOrder() {
        let snapshot = todaySnapshot(tasks: [
            task(order: 2, block: "sql", state: "in_progress", objective: "Join the orders", minutes: 45),
            task(order: 1, block: "technical_learning", state: "ready", objective: "Recall the trade-off", minutes: 30),
        ])

        XCTAssertEqual(
            CoachContext.summary(of: snapshot),
            "- Recall the trade-off (Technical Learning, ready, 30 min)\n- Join the orders (Sql, in progress, 45 min)"
        )
    }

    func testTheCoachNamesBlocksAndStatesExactlyAsTodayDoes() {
        let raw = [("career_pipeline", "output_committed"), ("tam_case", "ready")]
        let snapshot = todaySnapshot(tasks: raw.enumerated().map { index, pair in
            task(order: index, block: pair.0, state: pair.1, objective: "o", minutes: 5)
        })

        XCTAssertEqual(
            CoachContext.summary(of: snapshot),
            raw.map { "- o (\(TodayFormat.block($0.0)), \(TodayFormat.state($0.1)), 5 min)" }.joined(separator: "\n")
        )
    }

    func testTheStandingNamesTheBlockAndTheGuidesCurrentStep() {
        var activity = ActivityFixtures.detail(state: .active)
        activity.taskContract.block = .technicalLearning

        XCTAssertEqual(
            ActivityStanding.from(activity: activity),
            ActivityStanding(activityID: 41, block: "Technical Learning", stepLabel: "Hide the source", stepNumber: 2, stepCount: 6)
        )

        activity.state = .incomplete
        XCTAssertEqual(
            ActivityStanding.from(activity: activity),
            ActivityStanding(activityID: 41, block: "Technical Learning", stepLabel: nil, stepNumber: nil, stepCount: 6)
        )
    }

    func testTheLiveClientSendsTheContextsAndUsesTheGeneralRoutes() async throws {
        let fixture = URLProtocolFixture()
        let threadBody = Data("""
        {"activity_id": 41, "thread_id": 3, "coaching_allowed": true, "committed": false,
         "next_step": "Write your independent attempt.", "assistance_mode": "none", "messages": []}
        """.utf8)
        let generalBody = Data("""
        {"thread_id": 5, "messages": [{"id": 9, "speaker": "coach", "text": "Start with SQL.",
          "next_step": null, "proposed_evidence": [], "created_at": "2026-09-25T10:00:00Z"}]}
        """.utf8)
        fixture.enqueue(.response(statusCode: 200, body: threadBody))
        fixture.enqueue(.response(statusCode: 200, body: Data(#"{"thread_id": null, "messages": []}"#.utf8)))
        fixture.enqueue(.response(statusCode: 200, body: generalBody))
        let api = LiveCoachAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!, session: fixture.session()
        ))

        _ = try await api.send(
            activityID: 41, text: "hint?",
            context: CoachWorkingContext(step: "Do it", fields: [CoachDraftField(name: "attempt", value: "draft")])
        )
        let empty = try await api.generalThread()
        let general = try await api.sendGeneral(text: "hola", context: CoachScreenContext(screen: "Today", summary: "- a"))

        XCTAssertNil(empty.threadID)
        XCTAssertEqual(general.threadID, 5)
        XCTAssertEqual(general.messages.first?.text, "Start with SQL.")
        let requests = fixture.requests
        XCTAssertEqual(requests.map { "\($0.httpMethod ?? "") \($0.url?.path ?? "")" }, [
            "POST /api/v1/activities/41/coach/messages", "GET /api/v1/coach", "POST /api/v1/coach/messages",
        ])
        XCTAssertEqual(
            String(decoding: try requestBody(requests[0]), as: UTF8.self),
            #"{"context":{"fields":[{"name":"attempt","value":"draft"}],"step":"Do it"},"text":"hint?"}"#
        )
        XCTAssertEqual(
            String(decoding: try requestBody(requests[2]), as: UTF8.self),
            #"{"context":{"screen":"Today","summary":"- a"},"text":"hola"}"#
        )
    }

    func testTheLiveClientDecodesTheActivityThreadAndTranslatesProblems() async throws {
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
        XCTAssertNil(thread.assistanceMode)
        XCTAssertEqual(thread.messages.first?.proposedEvidence.first?.kind, "note")
        XCTAssertEqual(fixture.requests.first?.url?.path, "/api/v1/activities/41/coach")

        XCTAssertEqual(LiveCoachAPI.translate(.problem(problem(status: 503, code: "coach_unavailable"))), .unavailable)
        XCTAssertEqual(LiveCoachAPI.translate(.problem(problem(status: 401, code: nil))), .unauthorized)
        XCTAssertEqual(LiveCoachAPI.translate(.problem(problem(status: 403, code: "coaching_not_allowed"))), .notAllowed)
        XCTAssertEqual(LiveCoachAPI.translate(.problem(problem(status: 409, code: nil))), .conflict)
        XCTAssertEqual(LiveCoachAPI.translate(.decodingResponse), .invalidResponse)
    }

    // MARK: - Fixtures

    private func activityContext() -> CoachContext {
        let context = CoachContext()
        context.route = .activity(19)
        context.activity = ActivityStanding(
            activityID: 19, block: "Technical Learning", stepLabel: "Do it", stepNumber: 2, stepCount: 5
        )
        return context
    }

    private func problem(status: Int, code: String?) -> APIProblem {
        APIProblem(type: nil, title: nil, status: status, detail: nil, instance: nil, code: code)
    }

    private func requestBody(_ request: URLRequest) throws -> Data {
        if let body = request.httpBody { return body }
        let stream = try XCTUnwrap(request.httpBodyStream)
        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count == 0 { return body }
            if count < 0 { throw try XCTUnwrap(stream.streamError) }
            body.append(contentsOf: buffer.prefix(count))
        }
    }

    private func task(order: Int, block: String, state: String, objective: String, minutes: Int) -> TodayTask {
        TodayTask(
            activityID: order, roadmapOrder: order, stableID: "task-\(order)", block: block, state: state,
            objective: objective, timeboxMinutes: minutes, sourceReferences: [], requiredOutput: [], passCriteria: [],
            allowedAIRole: "coach", evidenceRequirements: [], required: true, optimisticVersion: 1
        )
    }

    private func todaySnapshot(tasks: [TodayTask]) -> TodaySnapshot {
        TodaySnapshot(
            localDate: "2026-09-25", timezone: "America/Montevideo", dayID: 1, dayType: "study", dayStatus: "open",
            roadmap: TodayRoadmap(versionID: 1, versionKey: "v1", versionNumber: 1, month: 1, week: 1, day: 1),
            totalPlannedMinutes: 75,
            timePolicy: TodayTimePolicy(
                targetMinutes: 75, acceptableMinimum: 45, hardStopMinutes: 120, focusedMinutes: 0, hardStopRecommended: false
            ),
            requiredBlocks: [], tasks: tasks, corrections: [], interviews: [], awaitingSelfReviews: [], analyses: [],
            primaryContinue: nil, sourceUpdatedAt: "2026-09-25T10:00:00Z", readModelVersion: "1", etag: "e"
        )
    }
}

@MainActor
private final class FakeCoachAPI: CoachAPI {
    var failure: CoachAPIError?
    var duringCall: (() -> Void)?
    var sendGate: ActivityTestGate?
    private(set) var calls: [String] = []
    private(set) var lastWorkingContext: CoachWorkingContext?
    private(set) var lastScreenContext: CoachScreenContext?

    func thread(activityID: Int) async throws -> CoachThread {
        try record("thread:\(activityID)")
        return activityThread(activityID)
    }

    func send(activityID: Int, text: String, context: CoachWorkingContext) async throws -> CoachThread {
        lastWorkingContext = context
        try record("send:\(activityID):\(text)")
        await sendGate?.wait()
        return activityThread(activityID)
    }

    func acceptEvidence(activityID: Int, messageID: Int, index: Int) async throws -> CoachThread {
        try record("evidence:\(activityID):\(messageID):\(index)")
        return activityThread(activityID)
    }

    func generalThread() async throws -> GeneralCoachThread {
        try record("general")
        return GeneralCoachThread(threadID: nil, messages: [])
    }

    func sendGeneral(text: String, context: CoachScreenContext) async throws -> GeneralCoachThread {
        lastScreenContext = context
        try record("sendGeneral:\(text)")
        return GeneralCoachThread(threadID: 5, messages: [
            CoachMessage(id: 1, speaker: "coach", text: "reply", nextStep: nil, proposedEvidence: [], createdAt: Date()),
        ])
    }

    private func record(_ call: String) throws {
        calls.append(call)
        duringCall?()
        if let failure { throw failure }
    }

    private func activityThread(_ activityID: Int) -> CoachThread {
        CoachThread(
            activityID: activityID, threadID: 3, coachingAllowed: true, committed: false,
            nextStep: "Write your independent attempt.", assistanceMode: "none", messages: [
                CoachMessage(id: 1, speaker: "coach", text: "thread \(activityID)", nextStep: nil, proposedEvidence: [], createdAt: Date()),
            ]
        )
    }
}
