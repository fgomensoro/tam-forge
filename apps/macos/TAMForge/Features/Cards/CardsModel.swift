import Foundation

/// The day's due cards, run one at a time: show the question, reveal the answer, grade it,
/// and the server reschedules it. Spoken mode records the answer aloud before the grade so
/// the review keeps its recording as evidence.
@MainActor
final class CardsModel: ObservableObject {
    enum Mode: String { case written, spoken }

    @Published private(set) var queue: [CardRecord] = []
    @Published private(set) var reviewedCount = 0
    @Published private(set) var isRevealed = false
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var lastOutcome: CardReviewOutcome?
    @Published private(set) var lastImport: CardImportOutcome?
    @Published var mode: Mode = .written
    @Published var draft = CardDraft.empty()
    @Published private(set) var spokenRecordingID: UUID?
    /// Free practice: every card the learner owns, the topic chosen, and whether the queue
    /// on screen is a practice round rather than the day's due cards.
    @Published private(set) var library: [CardRecord] = []
    @Published var practiceTopicID = PracticeTopic.allID
    @Published private(set) var isPracticing = false

    private let api: any CardAPI
    private let coordinator: RecordingCoordinator?
    private let today: () -> String
    private let shuffle: ([CardRecord]) -> [CardRecord]

    init(
        api: any CardAPI, coordinator: RecordingCoordinator? = nil,
        today: @escaping () -> String = { CardsModel.localDate() },
        shuffle: @escaping ([CardRecord]) -> [CardRecord] = { $0.shuffled() }
    ) {
        self.api = api
        self.coordinator = coordinator
        self.today = today
        self.shuffle = shuffle
    }

    static func localDate(now: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: now)
    }

    var current: CardRecord? { queue.first }
    var remaining: Int { queue.count }
    var canRecord: Bool { coordinator.map { !$0.phase.isActive } ?? false }
    var canGrade: Bool {
        guard current != nil, isRevealed, !isBusy else { return false }
        return mode == .written || spokenRecordingID != nil
    }
    var canCreate: Bool { draft.isValid && !isBusy }

    func load() async {
        await perform {
            self.queue = try await self.api.due(on: self.today())
            self.isRevealed = false
            self.spokenRecordingID = nil
        }
    }

    var practiceTopics: [PracticeTopic] { PracticeTopic.topics(for: library) }
    var canPractice: Bool { !isBusy && !PracticeTopic.cards(for: practiceTopicID, in: library).isEmpty }

    /// Every card the learner owns, for the topic picker. The due queue is untouched.
    func loadLibrary() async {
        await perform {
            self.library = try await self.api.all().filter { $0.status == "active" }
            if !self.practiceTopics.contains(where: { $0.id == self.practiceTopicID }) {
                self.practiceTopicID = PracticeTopic.allID
            }
        }
    }

    /// A practice round: the chosen topic's cards, shuffled, whatever their due date. Each
    /// grade is a real review, so a card answered well moves out and one answered badly
    /// comes back sooner; practice and the daily queue stay one schedule.
    func startPractice() async {
        guard !isBusy else { return }
        await perform {
            self.library = try await self.api.all().filter { $0.status == "active" }
            let cards = PracticeTopic.cards(for: self.practiceTopicID, in: self.library)
            guard !cards.isEmpty else { return }
            self.queue = self.shuffle(cards)
            self.isPracticing = true
            self.reviewedCount = 0
            self.lastOutcome = nil
            self.isRevealed = false
            self.spokenRecordingID = nil
        }
    }

    /// Back to the day's due cards.
    func stopPractice() async {
        isPracticing = false
        reviewedCount = 0
        lastOutcome = nil
        await load()
    }

    func reveal() { isRevealed = true }

    /// Spoken mode: record the answer aloud; the review carries this recording.
    func recordAnswer() async {
        guard let coordinator, canRecord else { return }
        await coordinator.start()
        spokenRecordingID = coordinator.lastRecordingID
    }

    func grade(_ grade: Int) async {
        guard let card = current, canGrade, (0...5).contains(grade) else { return }
        let recordingID = mode == .spoken ? spokenRecordingID : nil
        await perform {
            let outcome = try await self.api.review(
                cardID: card.id, grade: grade, reviewedOn: self.today(), mode: self.mode.rawValue,
                recordingID: recordingID
            )
            self.lastOutcome = outcome
            self.queue.removeFirst()
            self.reviewedCount += 1
            self.isRevealed = false
            self.spokenRecordingID = nil
        }
    }

    func create() async {
        guard canCreate else { return }
        let draft = self.draft
        await perform {
            let created = try await self.api.create(draft)
            if created.dueOn <= self.today(), !self.queue.contains(where: { $0.id == created.id }) {
                self.queue.append(created)
            }
            self.draft = .empty()
        }
    }

    func importRoadmapVersion(_ versionID: Int) async {
        await perform {
            self.lastImport = try await self.api.importRoadmapVersion(versionID)
            self.queue = try await self.api.due(on: self.today())
        }
    }

    func dismissError() { errorMessage = nil }

    private func perform(_ operation: @escaping () async throws -> Void) async {
        isBusy = true
        defer { isBusy = false }
        do {
            try await operation()
            errorMessage = nil
        } catch let error as CardAPIError {
            if error != .cancelled { errorMessage = error.message }
        } catch {
            errorMessage = CardAPIError.network.message
        }
    }
}
