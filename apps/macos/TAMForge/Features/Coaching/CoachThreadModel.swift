import Combine
import Foundation

/// What the screens tell the floating coach about where the owner is standing.
struct ActivityStanding: Equatable, Sendable {
    let activityID: Int
    /// The block's display name, e.g. "Technical Learning".
    let block: String
    /// The task guide's current step, e.g. "Do it".
    let stepLabel: String?
    /// 1-based.
    let stepNumber: Int?
    let stepCount: Int

    /// The standing the task guide shows at the top of the activity screen.
    static func from(activity: ActivityDetail) -> ActivityStanding {
        let steps = TaskGuide.steps(for: activity.taskContract.block)
        let current = TaskGuide.currentStep(for: activity)
        return ActivityStanding(
            activityID: activity.id,
            block: TodayFormat.block(activity.taskContract.block.rawValue),
            stepLabel: current.map { steps[$0] },
            stepNumber: current.map { $0 + 1 },
            stepCount: steps.count
        )
    }
}

/// Where the owner is in the app. The shell keeps the route and the day's plan; the
/// activity screen, while shown, adds its standing and a way to read its draft.
@MainActor
final class CoachContext: ObservableObject {
    @Published var route: ShellRoute = .today
    @Published var activity: ActivityStanding?
    @Published var todaySummary: String = ""
    /// Set by the activity screen while shown: the draft's fields. Blank ones are not sent.
    var draftFields: () -> [CoachDraftField] = { [] }

    /// The day's plan as the coach reads it: one line per task, in roadmap order.
    static func summary(of snapshot: TodaySnapshot) -> String {
        snapshot.tasks.sorted { $0.roadmapOrder < $1.roadmapOrder }.map { task in
            "- \(task.objective) (\(TodayFormat.block(task.block)), \(TodayFormat.state(task.state)), \(task.timeboxMinutes) min)"
        }
        .joined(separator: "\n")
    }
}

/// Drives the floating coach. On an activity route it talks to that activity's thread
/// and sends the step and the unsaved draft; on every other route it talks to the
/// owner's general thread and sends the screen. A thread is loaded only when the
/// coach is open, so a session that never asks the coach never touches its endpoints.
@MainActor
final class CoachThreadModel: ObservableObject {
    @Published var isPresented = false
    @Published var draft = ""
    @Published private(set) var activityThread: CoachThread?
    @Published private(set) var generalThread: GeneralCoachThread?
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?

    let context: CoachContext
    private let api: any CoachAPI
    private var contextObservation: AnyCancellable?
    /// Requests in flight. A reload that finishes during a send must not end the busy state.
    private var inFlight = 0 {
        didSet { isBusy = inFlight > 0 }
    }

    init(api: any CoachAPI, context: CoachContext) {
        self.api = api
        self.context = context
        // The title reads the context, so a view of this model follows the context too.
        contextObservation = context.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
    }

    var activityID: Int? {
        if case let .activity(identifier) = context.route { return identifier }
        return nil
    }

    var title: String {
        switch context.route {
        case .today: return "Today"
        case .roadmaps: return "Roadmaps"
        case .recording: return "Recording"
        case .interviews: return "Interviews"
        case .classes: return "English classes"
        case .cards: return "Cards"
        case .progress: return "Progress"
        case .evidence: return "Evidence"
        case let .activity(identifier):
            guard let standing else { return "Activity \(identifier)" }
            let step = standing.stepNumber.map { "Step \($0) of \(standing.stepCount)" }
            return ["Activity \(identifier)", step, standing.block].compactMap { $0 }.joined(separator: " · ")
        }
    }

    /// The loaded activity thread, only while it belongs to the activity on screen.
    var shownActivityThread: CoachThread? {
        guard let activityThread, activityThread.activityID == activityID else { return nil }
        return activityThread
    }

    var messages: [CoachMessage] {
        activityID == nil ? generalThread?.messages ?? [] : shownActivityThread?.messages ?? []
    }

    var canSend: Bool {
        !isBusy && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func toggle() async {
        isPresented.toggle()
        if isPresented { await reload() }
    }

    func reload() async {
        if let activityID {
            await perform { store(try await api.thread(activityID: activityID)) }
        } else {
            await perform { generalThread = try await api.generalThread() }
        }
    }

    func routeChanged() async {
        if activityThread?.activityID != activityID { activityThread = nil }
        if isPresented { await reload() }
    }

    func send() async {
        guard canSend else { return }
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let sent: Bool
        if let activityID {
            let working = workingContext()
            sent = await perform { store(try await api.send(activityID: activityID, text: text, context: working)) }
        } else {
            let summary = context.route == .today ? Self.clip(context.todaySummary, to: 4_000) : ""
            let screen = CoachScreenContext(screen: title, summary: summary)
            sent = await perform { generalThread = try await api.sendGeneral(text: text, context: screen) }
        }
        if sent { draft = "" }
    }

    func accept(messageID: Int, index: Int) async {
        guard let activityID, !isBusy else { return }
        await perform {
            store(try await api.acceptEvidence(activityID: activityID, messageID: messageID, index: index))
        }
    }

    func dismissError() {
        errorMessage = nil
    }

    private var standing: ActivityStanding? {
        guard let standing = context.activity, standing.activityID == activityID else { return nil }
        return standing
    }

    /// A late answer for an activity the owner already left is not this screen's thread.
    private func store(_ thread: CoachThread) {
        if thread.activityID == activityID { activityThread = thread }
    }

    /// The step and draft cut to what the server accepts (step 200, 20 fields, name 64,
    /// value 4000, 12000 in all), so a long draft still reaches the coach.
    private func workingContext() -> CoachWorkingContext {
        let step = Self.clip(standing?.stepLabel ?? "", to: 200)
        var budget = 12_000 - step.unicodeScalars.count
        var fields: [CoachDraftField] = []
        let written = context.draftFields().filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        for field in written.prefix(20) {
            let name = Self.clip(field.name, to: 64)
            let room = min(4_000, budget - name.unicodeScalars.count)
            guard room > 0 else { break }
            let value = Self.clip(field.value, to: room)
            fields.append(CoachDraftField(name: name, value: value))
            budget -= name.unicodeScalars.count + value.unicodeScalars.count
        }
        return CoachWorkingContext(step: step, fields: fields)
    }

    /// Counts Unicode scalars, as the server's length limits do.
    private static func clip(_ text: String, to limit: Int) -> String {
        String(String.UnicodeScalarView(text.unicodeScalars.prefix(limit)))
    }

    @discardableResult
    private func perform(_ operation: () async throws -> Void) async -> Bool {
        inFlight += 1
        defer { inFlight -= 1 }
        do {
            try await operation()
            errorMessage = nil
            return true
        } catch let error as CoachAPIError {
            if error != .cancelled { errorMessage = error.message }
            return false
        } catch {
            errorMessage = CoachAPIError.network.message
            return false
        }
    }
}
