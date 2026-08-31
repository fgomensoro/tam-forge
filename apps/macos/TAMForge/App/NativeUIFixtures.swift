#if DEBUG
import Foundation

/// Explicit UI-test launches exercise the real URLSession adapters without network or credentials.
final class NativeUIFixtureProtocol: URLProtocol, @unchecked Sendable {
    private static let state = NativeUIFixtureState()

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let data = try Self.state.response(for: request)
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil,
                                           headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

/// URLProtocol may invoke requests concurrently; all fixture state is protected by this lock.
private final class NativeUIFixtureState: @unchecked Sendable {
    private let lock = NSLock()
    private var activityState = ProcessInfo.processInfo.arguments.contains("-ui-test-self-review") ? "output_committed" : "ready"
    private var activityVersion = 1
    private var roadmapState: String?
    private var dayClosed = false
    private let closingDay = ProcessInfo.processInfo.arguments.contains("-ui-test-daily-close")
    private let reviewingEvidence = ProcessInfo.processInfo.arguments.contains("-ui-test-evidence-route")
    private let emptyEvidence = ProcessInfo.processInfo.arguments.contains("-ui-test-empty-evidence")
    private let keyboardEvidenceRefresh = ProcessInfo.processInfo.arguments.contains("-ui-test-evidence-keyboard-refresh")
    private var failSkillsOnce = ProcessInfo.processInfo.arguments.contains("-ui-test-evidence-retry")
    private var skillListRequests = 0
    private let stamp = "2026-08-27T20:00:00Z"

    func response(for request: URLRequest) throws -> Data {
        try lock.withLock {
            guard let url = request.url,
                  NativeUIFixtureRequestValidator.hasExpectedOrigin(
                    url,
                    environment: AppEnvironment.selected(from: ProcessInfo.processInfo.environment)
                  )
            else { throw URLError(.badURL) }
            let path = request.url?.path ?? ""
            if let evidence = try evidenceResponse(for: request) {
                return try JSONSerialization.data(withJSONObject: evidence)
            }
            let value: Any
            switch path {
            case "/api/v1/today":
                let date = request.url.flatMap { URLComponents(url: $0, resolvingAgainstBaseURL: false) }?
                    .queryItems?.first(where: { $0.name == "date" })?.value ?? "2026-08-27"
                value = today(localDate: date)
            case let path where path.hasPrefix("/api/v1/today/") && path.hasSuffix("/close"):
                dayClosed = true
                value = ["daily_close_id": 9, "study_day_id": 8, "day_status": "closed",
                         "closed_at": stamp, "consequence": "none", "replayed": false]
            case "/api/v1/notifications":
                value = ["items": [], "next_cursor": NSNull()]
            case "/api/v1/roadmap-imports":
                value = ["id": 17, "status": "validated", "failure_code": NSNull(),
                         "validation_report": ["accepted": true, "task_count": 1, "resource_count": 0,
                                               "exit_criterion_count": 1, "issues": []],
                         "semantic_diff": [
                            "summary": ["added": 0, "changed": 1, "removed": 0],
                            "tasks": ["entries": [["key": "ui-writing", "status": "changed", "fields": [
                                ["name": "objective", "before": "Write an update", "after": "Lead with customer impact"]
                            ]]]]
                         ]]
            case "/api/v1/roadmap-imports/17/approve":
                roadmapState = "approved"
                value = roadmap()
            case "/api/v1/roadmap-versions/8/activate":
                roadmapState = "active"
                value = roadmap()
            case "/api/v1/roadmap-versions":
                value = roadmapState == nil ? [] : [roadmap()]
            case "/api/v1/activities/41":
                value = activity()
            case "/api/v1/activities/41/start", "/api/v1/activities/41/resume":
                activityState = "active"
                activityVersion += 1
                value = activitySummary()
            case "/api/v1/activities/41/pause":
                activityState = "paused"
                activityVersion += 1
                value = activitySummary()
            case "/api/v1/activities/41/heartbeat":
                value = activitySummary()
            case "/api/v1/activities/41/self-review":
                activityState = "self_review_complete"
                activityVersion += 1
                value = ["activity_id": 41, "state": activityState, "optimistic_version": activityVersion,
                         "self_review_id": 12, "attempt_id": 11, "self_score": 0]
            default:
                throw URLError(.unsupportedURL)
            }
            return try JSONSerialization.data(withJSONObject: value)
        }
    }

    private func roadmap() -> [String: Any] {
        ["id": 8, "version_key": "month-1-v1", "version_number": 1, "month_number": 1,
         "state": roadmapState ?? "approved", "mirror_status": "not_required",
         "mirror_ref": NSNull(), "mirror_error_code": NSNull()]
    }

    private func today(localDate: String) -> [String: Any] {
        let task: [String: Any] = [
            "activity_id": 41, "roadmap_order": 1, "stable_id": "ui-writing",
            "block": "communication_spoken", "state": closingDay ? "self_review_complete" : activityState,
            "objective": "Write a concise customer update.", "timebox_minutes": 35,
            "source_references": [], "required_output": ["Independent draft"], "pass_criteria": ["Impact first"],
            "allowed_ai_role": "none", "evidence_requirements": ["Attempt A"], "required": true,
            "optimistic_version": activityVersion,
        ]
        let action: [String: Any] = [
            "kind": reviewingEvidence ? "review_feedback" : closingDay ? "close_day" : activityState == "output_committed" ? "complete_self_review" : "resume_activity",
            "target_id": closingDay ? 70 : 41,
            "label": reviewingEvidence ? "Review activity evidence" : closingDay ? "Close study day" : "Continue customer update", "allowed_ai_role": "none",
        ]
        return [
            "local_date": localDate, "timezone": "America/Los_Angeles", "day_id": 8,
            "day_type": "weekday", "day_status": dayClosed ? "closed" : "in_progress",
            "roadmap": ["version_id": 2, "version_key": "month-1-v1", "version_number": 1, "month": 1, "week": 1, "day": 4],
            "total_planned_minutes": 240,
            "time_policy": ["target_minutes": 240, "acceptable_minimum": 225, "hard_stop_minutes": 255,
                            "focused_minutes": 65, "hard_stop_recommended": false],
            "required_blocks": [], "tasks": [task], "corrections": [], "interviews": [],
            "awaiting_self_reviews": [], "analyses": [], "primary_continue": dayClosed ? NSNull() : action,
            "source_updated_at": stamp, "read_model_version": "ui-v1", "etag": "ui-v1",
        ]
    }

    private func activity() -> [String: Any] {
        [
            "id": 41, "study_day_id": 8, "state": activityState, "optimistic_version": activityVersion,
            "classification": "required", "stronger_evidence_id": NSNull(),
            "activity_focused_seconds": 120, "day_focused_minutes": 2, "hard_stop_recommended": false,
            "open_timer": activityState == "active" ? [
                "id": 7, "started_at": stamp, "last_heartbeat_at": stamp,
                "counted_seconds": 120, "last_client_sequence": 0,
            ] : NSNull(),
            "source_hidden": false,
            "task_contract": [
                "stable_id": "ui-writing", "block": "communication_spoken",
                "objective": "Write a concise customer update.", "timebox_minutes": 35, "required": true,
                "source_references": [], "required_output": ["Independent draft"], "pass_criteria": ["Impact first"],
                "evidence_requirements": ["Attempt A"], "allowed_ai_role": "none", "procedure": [],
                "constraints": ["No AI before commitment."], "exercise_type": "writing", "mapping_version": "ui-v1",
            ],
            "committed_output": ["output_committed", "self_review_complete"].contains(activityState) ? [
                "attempt_id": 11, "attempt_kind": "writing", "commitment_sha256": String(repeating: "a", count: 64),
                "contract_payload": ["output": ["draft_markdown": "Saved customer update."]],
                "artifact_ids": [], "committed_at": stamp,
            ] : NSNull(),
            "self_review": activityState == "self_review_complete" ? [
                "id": 12, "attempt_id": 11, "self_score": 0,
                "main_answer": "Clear impact.", "did_well": "Clear impact.", "structure_weakness": "Clear impact.",
                "vague_points": "Clear impact.", "hesitation_points": "Clear impact.", "change_next": "Clear impact.",
                "submitted_at": stamp,
            ] : NSNull(),
        ]
    }

    private func activitySummary() -> [String: Any] {
        // Command receipts use ActivityResponse, which rejects detail-only properties.
        activity().filter { !["task_contract", "committed_output", "self_review"].contains($0.key) }
    }

    /// Synthetic read contracts only. Unsupported scopes, methods and cursors fail closed.
    private func evidenceResponse(for request: URLRequest) throws -> Any? {
        let path = request.url?.path ?? ""
        let skillPath = "/api/v1/skills/structured_troubleshooting"
        let paths = ["/api/v1/skills", skillPath, "\(skillPath)/evidence",
                     "/api/v1/skills/tam_english", "/api/v1/skills/tam_english/evidence",
                     "/api/v1/activities/41/evidence", "/api/v1/portfolio-judgment"]
        guard paths.contains(path) else { return nil }
        guard request.httpMethod == "GET", request.httpBody == nil, request.httpBodyStream == nil,
              request.value(forHTTPHeaderField: "Authorization") == "Bearer ui-test-only",
              let url = request.url,
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw URLError(.badServerResponse)
        }
        let paginated = path.hasSuffix("/evidence") || path == "/api/v1/portfolio-judgment"
        let cursor: Int?
        do {
            cursor = try NativeEvidenceFixtureQuery.cursor(from: url, paginated: paginated)
        } catch {
            throw URLError(.badServerResponse)
        }
        switch path {
        case "/api/v1/skills":
            skillListRequests += 1
            if failSkillsOnce {
                failSkillsOnce = false
                throw URLError(.notConnectedToInternet)
            }
            let refreshed = keyboardEvidenceRefresh && skillListRequests > 1
            return ["items": [evidenceSkill(refreshed: refreshed), evidenceSkill(english: true)]]
        case skillPath:
            return evidenceSkill()
        case "/api/v1/skills/tam_english":
            return evidenceSkill(english: true)
        case "/api/v1/portfolio-judgment":
            guard cursor == nil || cursor == 91 else { throw URLError(.badServerResponse) }
            if emptyEvidence { return ["items": [], "next_cursor": NSNull()] }
            let score: [String: Any] = [
                "id": cursor == nil ? 91 : 90, "activity_id": 41, "attempt_id": 11,
                "formula_version": "seed-v1", "rubric_version": "seed-v1", "total_score": "14.000",
                "components": [
                    ["slug": "impact_risk_assessment", "score": "3.000"],
                    ["slug": "explicit_prioritization", "score": "2.000"],
                    ["slug": "delegation_ownership", "score": "2.000"],
                    ["slug": "communication_control", "score": "2.000"],
                    ["slug": "proactive_work_protection", "score": "1.000"],
                    ["slug": "evidence_based_reprioritization", "score": "2.000"],
                    ["slug": "english_clarity", "score": "2.000"],
                ],
                "trend_basis": ["schema_version": 1, "basis_code": "first_score", "event_ids": []],
                "scored_at": stamp,
            ]
            let nextCursor: Any = cursor == nil ? 91 : NSNull()
            return ["items": [score], "next_cursor": nextCursor]
        default:
            guard cursor == nil || cursor == 49 else { throw URLError(.badServerResponse) }
            if emptyEvidence || path.contains("tam_english") {
                return ["items": [], "next_cursor": NSNull()]
            }
            let events = cursor == nil ? [evidenceEvent(id: 50), evidenceEvent(id: 49)] : [evidenceEvent(id: 39)]
            let nextCursor: Any = cursor == nil ? 49 : NSNull()
            return ["items": events, "next_cursor": nextCursor]
        }
    }

    private func evidenceSkill(english: Bool = false, refreshed: Bool = false) -> [String: Any] {
        let assessed = !english && !emptyEvidence
        let snapshot: [String: Any] = [
            "id": 71, "formula_version": "seed-v1", "snapshot_date": "2026-08-27",
            "estimated_level": "2.750", "confidence": "medium", "trend": "improving", "recency": "fresh",
            "baseline_target_gap": "-0.750", "month_one_target_gap": "0.250", "final_target_gap": "0.750",
            "total_effective_weight": "1.400", "qualifying_event_count": 2, "exercise_type_count": 2,
            "last_strong_evidence_date": "2026-08-27",
            "manifest": [
                ["event_id": 50, "effective_weight": "0.400", "inclusion_code": "discounted_same_day"],
                ["event_id": 49, "effective_weight": "0.000", "inclusion_code": "excluded_nonqualifying"],
                ["event_id": 9, "effective_weight": "1.000", "inclusion_code": "included"],
            ],
            "confidence_basis": ["schema_version": 1, "qualifying_events": 2,
                                 "future_basis": ["context": ["Independent case", "Timed writing"]]],
            "trend_basis": ["schema_version": 1, "basis_code": "improving", "event_ids": [50, 9]],
        ]
        return [
            "slug": english ? "tam_english" : "structured_troubleshooting",
            "name": english ? "TAM English" : refreshed ? "Structured troubleshooting refreshed" : "Structured troubleshooting",
            "baseline": "2.000", "month_one_target": "3.000", "final_target": "3.500",
            "latest_snapshot": assessed ? snapshot : NSNull(),
        ]
    }

    private func evidenceEvent(id: Int) -> [String: Any] {
        let selfEvidence = id == 49
        return [
            "id": id, "activity_id": 41, "attempt_id": 11, "skill_slug": "structured_troubleshooting",
            "exercise_type": "troubleshooting_case", "mapping_version": "seed-v1", "formula_version": "seed-v1",
            "rubric_slug": "tam_case", "rubric_version": "seed-v1",
            "evaluator": selfEvidence ? "self" : "human_coach", "practice_mode": "independent_practice",
            "assistance": "no_ai", "difficulty": "standard", "performance_score": "3.000",
            "skill_impact": "1.000", "effective_weight": "0.800", "qualifying_for_level": !selfEvidence,
            "qualification_reason": selfEvidence ? "excluded_by_formula" : "qualifies",
            "raw_dimension_scores": ["schema_version": 1, "scores": [
                ["dimension_slug": "diagnosis", "availability": "scored", "score": "3.000",
                 "observations": ["Customer impact is explicit; next steps name an owner and a verification condition."]],
            ]],
            "occurred_at": stamp,
        ]
    }
}
#endif
