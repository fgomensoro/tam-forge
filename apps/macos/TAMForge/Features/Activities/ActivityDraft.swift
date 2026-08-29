import Foundation

enum ActivityOutputKind: String, CaseIterable, Codable, Equatable, Sendable {
    case reading
    case sql
    case `case`
    case writing
    case pipeline
}

struct ActivityDraft: Codable, Equatable, Sendable {
    private static let kindsByBlock: [ActivityBlock: [ActivityOutputKind]] = [
        .technicalLearning: [.reading],
        .sql: [.sql],
        .tamCase: [.`case`],
        .communicationSpoken: [.`case`, .writing],
        .careerPipeline: [.pipeline],
        .correctionWarmup: [.sql, .`case`, .writing],
        .dailyClose: [.writing],
        .saturdayAssessment: [.sql, .`case`, .writing],
    ]

    var kind: ActivityOutputKind
    private(set) var values: [String: String]

    static func empty(for activity: ActivityDetail, forcedKind: ActivityOutputKind? = nil) -> Self {
        let allowed = allowedKinds(for: activity.taskContract.block)
        let kind = forcedKind.flatMap { allowed.contains($0) ? $0 : nil } ?? preferredKind(for: activity, allowed: allowed)
        return .init(kind: kind, values: [
            "prompt": activity.taskContract.objective,
            "audience": "",
            "key_idea_1": "", "key_idea_2": "", "key_idea_3": "", "boundary_or_failure": "", "tam_customer_example": "", "unresolved_question": "",
            "query": "", "result": "", "validation": "", "explanation": "", "business_meaning": "", "assistance_used": "none",
            "canonical_prompt": activity.taskContract.objective, "canonical_facts": "", "discovery_questions": "", "assumptions": "", "working_notes": "", "final_artifact": "", "decisions": "", "risks": "", "unresolved_questions": "",
            "requested_action": "", "facts": "", "unknowns": "", "tone": "", "word_or_character_limit": "", "draft_markdown": "", "self_edit_notes": "",
            "company": "", "role": "", "stage": "", "completed_action": "", "artifact_summary": "", "next_action": "",
        ])
    }

    static func allowedKinds(for block: ActivityBlock) -> [ActivityOutputKind] {
        kindsByBlock[block] ?? [.writing]
    }

    func value(for key: String) -> String {
        values[key] ?? ""
    }

    func setting(_ key: String, to value: String) -> Self {
        var copy = self
        copy.values[key] = value
        return copy
    }

    func changingKind(to kind: ActivityOutputKind, for activity: ActivityDetail) -> Self {
        Self.empty(for: activity, forcedKind: kind)
    }

    func isComplete(for activity: ActivityDetail) -> Bool {
        output(for: activity) != nil
    }

    func output(for activity: ActivityDetail) -> [String: ActivityJSONValue]? {
        guard Self.allowedKinds(for: activity.taskContract.block).contains(kind) else { return nil }
        guard let prompt = nonBlank("prompt"), let audience = nonBlank("audience") else { return nil }
        var output: [String: ActivityJSONValue] = [
            "contract_version": .integer(1),
            "kind": .string(kind.rawValue),
            "prompt": .string(prompt),
            "audience": .string(audience),
            "time_limit_minutes": .integer(activity.taskContract.timeboxMinutes),
        ]

        switch kind {
        case .reading:
            guard let keyIdea1 = nonBlank("key_idea_1"),
                  let keyIdea2 = nonBlank("key_idea_2"),
                  let keyIdea3 = nonBlank("key_idea_3"),
                  let boundary = nonBlank("boundary_or_failure"),
                  let example = nonBlank("tam_customer_example"),
                  let question = nonBlank("unresolved_question")
            else { return nil }
            output["key_ideas"] = .array([.string(keyIdea1), .string(keyIdea2), .string(keyIdea3)])
            output["boundary_or_failure"] = .string(boundary)
            output["tam_customer_example"] = .string(example)
            output["unresolved_question"] = .string(question)
        case .sql:
            guard let query = nonBlank("query"),
                  let result = nonBlank("result"),
                  let validation = nonBlank("validation"),
                  let explanation = nonBlank("explanation"),
                  let meaning = nonBlank("business_meaning")
            else { return nil }
            output["query"] = .string(query)
            output["result"] = .string(result)
            output["validation"] = .string(validation)
            output["explanation"] = .string(explanation)
            output["business_meaning"] = .string(meaning)
            output["solving_seconds"] = .integer(min(activity.activityFocusedSeconds, activity.taskContract.timeboxMinutes * 60))
            output["assistance_used"] = .string(value(for: "assistance_used"))
        case .`case`:
            guard let canonicalPrompt = nonBlank("canonical_prompt"),
                  let facts = nonBlankLines("canonical_facts"),
                  let discovery = nonBlankLines("discovery_questions"),
                  let assumptions = nonBlankLines("assumptions"),
                  let notes = nonBlank("working_notes"),
                  let artifact = nonBlank("final_artifact"),
                  let decisions = nonBlankLines("decisions"),
                  let risks = nonBlankLines("risks"),
                  let unresolved = nonBlankLines("unresolved_questions")
            else { return nil }
            output["canonical_prompt"] = .string(canonicalPrompt)
            output["canonical_facts"] = .array(facts.map(ActivityJSONValue.string))
            output["discovery_questions"] = .array(discovery.map(ActivityJSONValue.string))
            output["assumptions"] = .array(assumptions.map(ActivityJSONValue.string))
            output["working_notes"] = .string(notes)
            output["final_artifact"] = .string(artifact)
            output["decisions"] = .array(decisions.map(ActivityJSONValue.string))
            output["risks"] = .array(risks.map(ActivityJSONValue.string))
            output["unresolved_questions"] = .array(unresolved.map(ActivityJSONValue.string))
        case .writing:
            guard let action = nonBlank("requested_action"),
                  let facts = nonBlankLines("facts"),
                  let unknowns = nonBlankLines("unknowns"),
                  let tone = nonBlank("tone"),
                  let limit = nonBlank("word_or_character_limit"),
                  let markdown = nonBlank("draft_markdown"),
                  let notes = nonBlank("self_edit_notes")
            else { return nil }
            output["requested_action"] = .string(action)
            output["facts"] = .array(facts.map(ActivityJSONValue.string))
            output["unknowns"] = .array(unknowns.map(ActivityJSONValue.string))
            output["tone"] = .string(tone)
            output["word_or_character_limit"] = .string(limit)
            output["draft_markdown"] = .string(markdown)
            output["self_edit_notes"] = .string(notes)
        case .pipeline:
            guard let company = nonBlank("company"),
                  let role = nonBlank("role"),
                  let stage = nonBlank("stage"),
                  let completed = nonBlank("completed_action"),
                  let artifact = nonBlank("artifact_summary"),
                  let next = nonBlank("next_action")
            else { return nil }
            output["company"] = .string(company)
            output["role"] = .string(role)
            output["stage"] = .string(stage)
            output["completed_action"] = .string(completed)
            output["artifact_summary"] = .string(artifact)
            output["next_action"] = .string(next)
        }
        return output
    }

    private static func preferredKind(for activity: ActivityDetail, allowed: [ActivityOutputKind]) -> ActivityOutputKind {
        let hint = (activity.taskContract.exerciseType ?? "").lowercased()
        return allowed.first(where: { hint.contains($0.rawValue) }) ?? allowed[0]
    }

    private func nonBlank(_ key: String) -> String? {
        let value = value(for: key).trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    private func nonBlankLines(_ key: String) -> [String]? {
        let lines = value(for: key)
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        return lines.isEmpty ? nil : lines
    }
}

@MainActor
protocol ActivityDraftStoring: AnyObject {
    func load(activityID: Int) -> ActivityDraft?
    func save(_ draft: ActivityDraft, activityID: Int)
    func remove(activityID: Int)
}

@MainActor
final class InMemoryActivityDraftStore: ActivityDraftStoring {
    private var drafts: [Int: ActivityDraft] = [:]

    func load(activityID: Int) -> ActivityDraft? { drafts[activityID] }
    func save(_ draft: ActivityDraft, activityID: Int) { drafts[activityID] = draft }
    func remove(activityID: Int) { drafts.removeValue(forKey: activityID) }
}

@MainActor
final class UserDefaultsActivityDraftStore: ActivityDraftStoring {
    private let defaults: UserDefaults
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func load(activityID: Int) -> ActivityDraft? {
        guard let data = defaults.data(forKey: key(activityID)) else { return nil }
        return try? decoder.decode(ActivityDraft.self, from: data)
    }

    func save(_ draft: ActivityDraft, activityID: Int) {
        guard let data = try? encoder.encode(draft) else { return }
        defaults.set(data, forKey: key(activityID))
    }

    func remove(activityID: Int) {
        defaults.removeObject(forKey: key(activityID))
    }

    private func key(_ activityID: Int) -> String {
        "tamforge.activity.\(activityID).draft.v1"
    }
}
