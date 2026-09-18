import Foundation

/// One flashcard as the server keeps it, with where it came from and when it is due.
struct CardRecord: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let question: String
    let answer: String
    let skillSlug: String
    let sourceKind: String
    let sourceRef: String
    let assistance: String
    let status: String
    let schedulerVersion: String
    let easiness: Decimal
    let intervalDays: Int
    let repetitions: Int
    let dueOn: String
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, question, answer, assistance, status, easiness, repetitions
        case skillSlug = "skill_slug"
        case sourceKind = "source_kind"
        case sourceRef = "source_ref"
        case schedulerVersion = "scheduler_version"
        case intervalDays = "interval_days"
        case dueOn = "due_on"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(
        id: Int, question: String, answer: String, skillSlug: String, sourceKind: String = "manual",
        sourceRef: String = "", assistance: String = "independent", status: String = "active",
        schedulerVersion: String = "sm2-v1", easiness: Decimal = 2.5, intervalDays: Int = 0,
        repetitions: Int = 0, dueOn: String, createdAt: Date = Date(timeIntervalSince1970: 0),
        updatedAt: Date = Date(timeIntervalSince1970: 0)
    ) {
        self.id = id
        self.question = question
        self.answer = answer
        self.skillSlug = skillSlug
        self.sourceKind = sourceKind
        self.sourceRef = sourceRef
        self.assistance = assistance
        self.status = status
        self.schedulerVersion = schedulerVersion
        self.easiness = easiness
        self.intervalDays = intervalDays
        self.repetitions = repetitions
        self.dueOn = dueOn
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(Int.self, forKey: .id)
        question = try container.decode(String.self, forKey: .question)
        answer = try container.decode(String.self, forKey: .answer)
        skillSlug = try container.decode(String.self, forKey: .skillSlug)
        sourceKind = try container.decode(String.self, forKey: .sourceKind)
        sourceRef = try container.decode(String.self, forKey: .sourceRef)
        assistance = try container.decode(String.self, forKey: .assistance)
        status = try container.decode(String.self, forKey: .status)
        schedulerVersion = try container.decode(String.self, forKey: .schedulerVersion)
        easiness = try Self.decimal(container, .easiness)
        intervalDays = try container.decode(Int.self, forKey: .intervalDays)
        repetitions = try container.decode(Int.self, forKey: .repetitions)
        dueOn = try container.decode(String.self, forKey: .dueOn)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        updatedAt = try container.decode(Date.self, forKey: .updatedAt)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(question, forKey: .question)
        try container.encode(answer, forKey: .answer)
        try container.encode(skillSlug, forKey: .skillSlug)
        try container.encode(sourceKind, forKey: .sourceKind)
        try container.encode(sourceRef, forKey: .sourceRef)
        try container.encode(assistance, forKey: .assistance)
        try container.encode(status, forKey: .status)
        try container.encode(schedulerVersion, forKey: .schedulerVersion)
        try container.encode("\(easiness)", forKey: .easiness)
        try container.encode(intervalDays, forKey: .intervalDays)
        try container.encode(repetitions, forKey: .repetitions)
        try container.encode(dueOn, forKey: .dueOn)
        try container.encode(createdAt, forKey: .createdAt)
        try container.encode(updatedAt, forKey: .updatedAt)
    }

    /// The server sends decimals as strings so no precision is lost; older payloads sent numbers.
    private static func decimal(_ container: KeyedDecodingContainer<CodingKeys>, _ key: CodingKeys) throws -> Decimal {
        if let text = try? container.decode(String.self, forKey: key), let value = Decimal(string: text) {
            return value
        }
        return try container.decode(Decimal.self, forKey: key)
    }
}

/// A card typed by hand in the app.
struct CardDraft: Codable, Equatable, Sendable {
    var question: String
    var answer: String
    var skillSlug: String

    static func empty() -> CardDraft { CardDraft(question: "", answer: "", skillSlug: "general") }

    var isValid: Bool {
        !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && skillSlug.range(of: "^[a-z][a-z0-9_]*$", options: .regularExpression) != nil
    }

    enum CodingKeys: String, CodingKey {
        case question, answer
        case skillSlug = "skill_slug"
    }
}

/// What the server answered after a grade: the rescheduled card and the review it wrote.
struct CardReviewOutcome: Codable, Equatable, Sendable {
    let card: CardRecord
    let intervalAfter: Int
    let dueAfter: String

    init(card: CardRecord, intervalAfter: Int, dueAfter: String) {
        self.card = card
        self.intervalAfter = intervalAfter
        self.dueAfter = dueAfter
    }

    private enum CodingKeys: String, CodingKey { case card, review }
    private enum ReviewKeys: String, CodingKey {
        case intervalAfter = "interval_after"
        case dueAfter = "due_after"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        card = try container.decode(CardRecord.self, forKey: .card)
        let review = try container.nestedContainer(keyedBy: ReviewKeys.self, forKey: .review)
        intervalAfter = try review.decode(Int.self, forKey: .intervalAfter)
        dueAfter = try review.decode(String.self, forKey: .dueAfter)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(card, forKey: .card)
        var review = container.nestedContainer(keyedBy: ReviewKeys.self, forKey: .review)
        try review.encode(intervalAfter, forKey: .intervalAfter)
        try review.encode(dueAfter, forKey: .dueAfter)
    }
}

struct CardImportOutcome: Codable, Equatable, Sendable {
    let sourceRef: String
    let created: Int
    let existing: Int

    enum CodingKeys: String, CodingKey {
        case created, existing
        case sourceRef = "source_ref"
    }
}

enum CardAPIError: Error, Equatable {
    case unauthorized
    case notFound
    case invalid
    case unavailable
    case invalidResponse
    case network
    case cancelled

    var message: String {
        switch self {
        case .unauthorized: "Sign in again to review cards."
        case .notFound: "That card, recording or roadmap version was not found on the server."
        case .invalid: "The server refused that card command."
        case .unavailable: "Cards are unavailable right now. Try again later."
        case .invalidResponse: "The server answered in a form this app cannot read."
        case .network: "The server could not be reached. Check the connection and try again."
        case .cancelled: "The request was cancelled."
        }
    }
}

/// What a free practice round draws from: every card, one skill, or one source note.
struct PracticeTopic: Equatable, Hashable, Sendable, Identifiable {
    static let allID = "all"

    let id: String
    let title: String
    let count: Int

    /// The topics a set of cards offers, largest first within skills and within notes.
    /// A skill is listed only when it tells cards apart; notes are listed by their title.
    static func topics(for cards: [CardRecord]) -> [PracticeTopic] {
        guard !cards.isEmpty else { return [] }
        var result = [PracticeTopic(id: allID, title: "All cards, mixed", count: cards.count)]
        let bySkill = Dictionary(grouping: cards, by: \.skillSlug)
        if bySkill.count > 1 {
            result += bySkill
                .map { PracticeTopic(id: "skill:\($0.key)", title: skillTitle($0.key), count: $0.value.count) }
                .sorted { ($0.count, $1.title) > ($1.count, $0.title) }
        }
        let bySource = Dictionary(grouping: cards.filter { !$0.sourceRef.isEmpty }, by: \.sourceRef)
        if bySource.count > 1 {
            result += bySource
                .map { PracticeTopic(id: "source:\($0.key)", title: sourceTitle($0.key), count: $0.value.count) }
                .sorted { ($0.count, $1.title) > ($1.count, $0.title) }
        }
        return result
    }

    static func cards(for topicID: String, in cards: [CardRecord]) -> [CardRecord] {
        if let skill = topicID.removingPrefix("skill:") { return cards.filter { $0.skillSlug == skill } }
        if let source = topicID.removingPrefix("source:") { return cards.filter { $0.sourceRef == source } }
        return cards
    }

    static func skillTitle(_ slug: String) -> String {
        slug.replacingOccurrences(of: "_", with: " ").capitalized
    }

    /// "package:study-notes/2026-09-16 - Retries Backoff and Jitter Study Notes.md" reads as
    /// "Retries Backoff and Jitter".
    static func sourceTitle(_ sourceRef: String) -> String {
        var name = sourceRef.split(separator: "/").last.map(String.init) ?? sourceRef
        if let colon = name.firstIndex(of: ":"), !name.contains("/") { name = String(name[name.index(after: colon)...]) }
        if name.lowercased().hasSuffix(".md") { name = String(name.dropLast(3)) }
        if let range = name.range(of: #"^\d{4}-\d{2}-\d{2}\s*-\s*"#, options: .regularExpression) {
            name.removeSubrange(range)
        }
        for suffix in [" Study Notes", " Practice Notes"] where name.hasSuffix(suffix) {
            name = String(name.dropLast(suffix.count))
        }
        return name.isEmpty ? sourceRef : name
    }
}

private extension String {
    func removingPrefix(_ prefix: String) -> String? {
        hasPrefix(prefix) ? String(dropFirst(prefix.count)) : nil
    }
}
