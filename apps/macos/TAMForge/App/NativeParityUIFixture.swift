#if DEBUG
import CryptoKit
import Foundation

enum NativeParityFixtureError: Error {
    case invalidFixture
    case invalidRequest
}

/// One strict DEBUG-only server for the native parity journey. Its payload comes from
/// the shared backend/Swift fixture; production builds compile this file to nothing.
final class NativeParityUIFixture {
    private let payload: NativeParityFixturePayload
    private var roadmapState: String?
    private var activityState = "ready"
    private var activityVersion = 1
    private var sourceHidden = false
    private var committedOutput: [String: Any]?
    private var submittedReview: [String: Any]?
    private var notificationReadAt: String?

    init(environment: [String: String] = ProcessInfo.processInfo.environment) throws {
        payload = try NativeParityFixturePayload(environment: environment)
    }

    static func fixedNow(
        arguments: [String] = ProcessInfo.processInfo.arguments,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Date? {
        guard arguments.contains("-ui-test-parity-journey") else { return nil }
        return try? NativeParityFixturePayload(environment: environment).fixedNow
    }

    func response(
        for request: URLRequest,
        environment: AppEnvironment
    ) throws -> Any {
        guard let url = request.url,
              NativeUIFixtureRequestValidator.hasExpectedOrigin(url, environment: environment),
              request.value(forHTTPHeaderField: "Authorization") == "Bearer ui-test-only"
        else { throw NativeParityFixtureError.invalidRequest }

        let path = url.path
        switch (request.httpMethod, path) {
        case ("GET", "/api/v1/today"):
            try requireRead(request)
            guard query(url) == ["date": payload.localDate] else { throw NativeParityFixtureError.invalidRequest }
            return today()
        case ("GET", "/api/v1/notifications"):
            try requireRead(request)
            guard query(url) == ["limit": "100"] else { throw NativeParityFixtureError.invalidRequest }
            return notifications()
        case ("POST", "/api/v1/notifications/61/read"):
            try requireCommand(request, idempotency: false, body: false)
            notificationReadAt = payload.stamp
            return notification()
        case ("GET", "/api/v1/roadmap-versions"):
            try requireRead(request)
            guard query(url).isEmpty else { throw NativeParityFixtureError.invalidRequest }
            return roadmapState == nil ? [] : [roadmap()]
        case ("POST", "/api/v1/roadmap-imports"):
            try requireCommand(request, idempotency: true, body: true)
            try validateRoadmapPackage(request)
            return payload.response("roadmap_import")
        case ("POST", "/api/v1/roadmap-imports/17/approve"):
            try requireCommand(request, idempotency: false, body: false)
            roadmapState = "approved"
            return roadmap()
        case ("POST", "/api/v1/roadmap-versions/8/activate"):
            try requireCommand(request, idempotency: false, body: false)
            guard roadmapState == "approved" else { throw NativeParityFixtureError.invalidRequest }
            roadmapState = "active"
            return roadmap()
        case ("GET", "/api/v1/activities/41"):
            try requireRead(request)
            guard query(url).isEmpty else { throw NativeParityFixtureError.invalidRequest }
            return activity()
        case ("POST", "/api/v1/activities/41/start"):
            try validateVersionedCommand(request, expectedState: "ready")
            activityState = "active"
            activityVersion += 1
            return activitySummary()
        case ("POST", "/api/v1/activities/41/pause"):
            try validateHeartbeatCommand(request, expectedState: "active")
            activityState = "paused"
            activityVersion += 1
            return activitySummary()
        case ("POST", "/api/v1/activities/41/resume"):
            try validateVersionedCommand(request, expectedState: "paused")
            activityState = "active"
            activityVersion += 1
            return activitySummary()
        case ("POST", "/api/v1/activities/41/heartbeat"):
            try validateHeartbeatCommand(request, expectedState: "active")
            return activitySummary()
        case ("POST", "/api/v1/activities/41/source-visibility"):
            let body = try commandBody(request)
            guard activityState == "active",
                  body.keys.sorted() == ["expected_version", "hidden"],
                  body["expected_version"] as? Int == activityVersion,
                  body["hidden"] as? Bool == true
            else { throw NativeParityFixtureError.invalidRequest }
            sourceHidden = true
            activityVersion += 1
            return activity()
        case ("POST", "/api/v1/activities/41/commit-output"):
            let body = try commandBody(request)
            guard activityState == "active",
                  body.keys.sorted() == ["artifact_refs", "client_sequence", "expected_version", "output"],
                  body["expected_version"] as? Int == activityVersion,
                  (body["client_sequence"] as? Int).map({ $0 >= 0 }) == true,
                  (body["artifact_refs"] as? [Any])?.isEmpty == true,
                  let output = body["output"] as? [String: Any],
                  try equivalentJSON(output, payload.output)
            else { throw NativeParityFixtureError.invalidRequest }
            activityState = "output_committed"
            activityVersion += 1
            committedOutput = output
            return [
                "activity_id": 41, "state": activityState, "optimistic_version": activityVersion,
                "attempt_id": 11, "commitment_sha256": String(repeating: "a", count: 64),
                "artifact_ids": [],
            ]
        case ("POST", "/api/v1/activities/41/self-review"):
            let body = try commandBody(request)
            var expected = payload.selfReview
            expected["expected_version"] = activityVersion
            guard activityState == "output_committed", try equivalentJSON(body, expected)
            else { throw NativeParityFixtureError.invalidRequest }
            activityState = "self_review_complete"
            activityVersion += 1
            submittedReview = payload.selfReview
            return [
                "activity_id": 41, "state": activityState, "optimistic_version": activityVersion,
                "self_review_id": 12, "attempt_id": 11, "self_score": 3,
            ]
        case ("GET", "/api/v1/skills"):
            try requireRead(request)
            guard query(url).isEmpty else { throw NativeParityFixtureError.invalidRequest }
            return payload.response("skills")
        case ("GET", "/api/v1/portfolio-judgment"):
            try requireRead(request)
            guard query(url) == ["limit": "20"] else { throw NativeParityFixtureError.invalidRequest }
            return payload.response("portfolio")
        default:
            throw NativeParityFixtureError.invalidRequest
        }
    }

    private func today() -> [String: Any] {
        var value = payload.response("today")
        if var tasks = value["tasks"] as? [[String: Any]], !tasks.isEmpty {
            tasks[0]["state"] = activityState
            tasks[0]["optimistic_version"] = activityVersion
            value["tasks"] = tasks
        }
        return value
    }

    private func roadmap() -> [String: Any] {
        var value = payload.response("roadmap_version")
        value["state"] = roadmapState ?? "approved"
        return value
    }

    private func activity() -> [String: Any] {
        var value = payload.response("activity")
        value["state"] = activityState
        value["optimistic_version"] = activityVersion
        value["source_hidden"] = sourceHidden
        value["activity_focused_seconds"] = activityState == "ready" ? 0 : 120
        value["day_focused_minutes"] = activityState == "ready" ? 0 : 2
        value["open_timer"] = activityState == "active" ? [
            "id": 7, "started_at": payload.stamp, "last_heartbeat_at": payload.stamp,
            "counted_seconds": 120, "last_client_sequence": 0,
        ] : NSNull()
        if let committedOutput {
            value["committed_output"] = [
                "attempt_id": 11, "attempt_kind": "reading",
                "commitment_sha256": String(repeating: "a", count: 64),
                "contract_payload": ["output": committedOutput], "artifact_ids": [],
                "committed_at": payload.stamp,
            ]
        }
        if let submittedReview {
            value["self_review"] = [
                "id": 12, "attempt_id": 11, "self_score": 3,
                "main_answer": submittedReview["main_answer"] as? String ?? "",
                "did_well": submittedReview["did_well"] as? String ?? "",
                "structure_weakness": submittedReview["structure_weakness"] as? String ?? "",
                "vague_points": submittedReview["vague_points"] as? String ?? "",
                "hesitation_points": submittedReview["hesitation_points"] as? String ?? "",
                "change_next": submittedReview["change_next"] as? String ?? "",
                "submitted_at": payload.stamp,
            ]
        }
        return value
    }

    private func activitySummary() -> [String: Any] {
        activity().filter { !["task_contract", "committed_output", "self_review"].contains($0.key) }
    }

    private func notifications() -> [String: Any] {
        var value = payload.response("notifications")
        value["items"] = [notification()]
        return value
    }

    private func notification() -> [String: Any] {
        var item = (payload.response("notifications")["items"] as? [[String: Any]])?.first ?? [:]
        item["read_at"] = notificationReadAt ?? NSNull()
        return item
    }

    private func validateVersionedCommand(_ request: URLRequest, expectedState: String) throws {
        let body = try commandBody(request)
        guard activityState == expectedState,
              body.keys.sorted() == ["expected_version"],
              body["expected_version"] as? Int == activityVersion
        else { throw NativeParityFixtureError.invalidRequest }
    }

    private func validateHeartbeatCommand(_ request: URLRequest, expectedState: String) throws {
        let body = try commandBody(request)
        guard activityState == expectedState,
              body.keys.sorted() == ["client_sequence", "expected_version"],
              body["expected_version"] as? Int == activityVersion,
              (body["client_sequence"] as? Int).map({ $0 >= 0 }) == true
        else { throw NativeParityFixtureError.invalidRequest }
    }

    private func commandBody(_ request: URLRequest) throws -> [String: Any] {
        try requireCommand(request, idempotency: true, body: true)
        guard request.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("application/json") == true,
              let value = try JSONSerialization.jsonObject(with: requestData(request)) as? [String: Any]
        else { throw NativeParityFixtureError.invalidRequest }
        return value
    }

    private func validateRoadmapPackage(_ request: URLRequest) throws {
        guard let contentType = request.value(forHTTPHeaderField: "Content-Type"),
              contentType.hasPrefix("multipart/form-data; boundary="),
              let boundary = contentType.components(separatedBy: "boundary=").last,
              !boundary.isEmpty
        else { throw NativeParityFixtureError.invalidRequest }
        let body = try requestData(request)
        let kindPart = Data("Content-Disposition: form-data; name=\"package_kind\"\r\n\r\nzip\r\n".utf8)
        let fileHeader = Data(
            "Content-Disposition: form-data; name=\"package\"; filename=\"roadmap-file\"\r\nContent-Type: application/octet-stream\r\n\r\n".utf8
        )
        let closing = Data("\r\n--\(boundary)".utf8)
        guard body.range(of: kindPart) != nil,
              let header = body.range(of: fileHeader),
              let contentEnd = body.range(of: closing, in: header.upperBound..<body.endIndex)
        else { throw NativeParityFixtureError.invalidRequest }
        let package = Data(body[header.upperBound..<contentEnd.lowerBound])
        guard package.count == payload.sourceByteLength,
              SHA256.hash(data: package).hex == payload.sourceSHA256
        else { throw NativeParityFixtureError.invalidRequest }
    }

    private func requireRead(_ request: URLRequest) throws {
        guard request.httpBody == nil, request.httpBodyStream == nil,
              request.value(forHTTPHeaderField: "Idempotency-Key") == nil
        else { throw NativeParityFixtureError.invalidRequest }
    }

    private func requireCommand(_ request: URLRequest, idempotency: Bool, body: Bool) throws {
        let key = request.value(forHTTPHeaderField: "Idempotency-Key")
        guard (idempotency ? key?.isEmpty == false : key == nil) else {
            throw NativeParityFixtureError.invalidRequest
        }
        if !body, request.httpBody != nil || request.httpBodyStream != nil {
            throw NativeParityFixtureError.invalidRequest
        }
    }

    private func requestData(_ request: URLRequest) throws -> Data {
        if let data = request.httpBody { return data }
        guard let stream = request.httpBodyStream else { throw NativeParityFixtureError.invalidRequest }
        stream.open()
        defer { stream.close() }
        var result = Data()
        var buffer = [UInt8](repeating: 0, count: 64 * 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count >= 0, result.count + count <= 65 * 1024 * 1024 else {
                throw NativeParityFixtureError.invalidRequest
            }
            if count == 0 { break }
            result.append(buffer, count: count)
        }
        guard !result.isEmpty else { throw NativeParityFixtureError.invalidRequest }
        return result
    }

    private func query(_ url: URL) -> [String: String] {
        var values: [String: String] = [:]
        for item in URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? [] {
            guard let value = item.value, values.updateValue(value, forKey: item.name) == nil else {
                return ["__invalid_query__": ""]
            }
        }
        return values
    }

    private func equivalentJSON(_ lhs: Any, _ rhs: Any) throws -> Bool {
        let left = try JSONSerialization.data(withJSONObject: lhs, options: [.sortedKeys])
        let right = try JSONSerialization.data(withJSONObject: rhs, options: [.sortedKeys])
        return left == right
    }
}

private struct NativeParityFixturePayload {
    let fixedNow: Date
    let localDate: String
    let sourceSHA256: String
    let sourceByteLength: Int
    let responses: [String: [String: Any]]
    let output: [String: Any]
    let selfReview: [String: Any]
    let stamp = "2026-08-24T20:00:00Z"

    init(environment: [String: String]) throws {
        guard let encoded = environment["TAMFORGE_UI_FIXTURE_BASE64"],
              let data = Data(base64Encoded: encoded),
              let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              root["schema_version"] as? Int == 1,
              root["scenario_id"] as? String == "native-foundation-month1-v1",
              let fixed = root["fixed_now"] as? String,
              let date = NativeJSONCodec.date(fixed),
              let source = root["source_package"] as? [String: Any],
              source["path"] as? String == "apps/backend/tests/fixtures/roadmaps/month-v1.zip",
              let sha = source["sha256"] as? String,
              let byteLength = source["byte_length"] as? Int,
              let rawResponses = root["responses"] as? [String: Any],
              Set(rawResponses.keys) == Set(["roadmap_import", "roadmap_version", "today", "activity", "notifications", "skills", "portfolio"]),
              let journey = root["journey"] as? [String: Any],
              let output = journey["output"] as? [String: Any],
              let selfReview = journey["self_review"] as? [String: Any],
              Set(selfReview.keys) == Set(["main_answer", "did_well", "structure_weakness", "vague_points", "hesitation_points", "change_next", "self_score"]),
              selfReview["self_score"] as? Int == 3,
              ["main_answer", "did_well", "structure_weakness", "vague_points", "hesitation_points", "change_next"]
                .allSatisfy({ (selfReview[$0] as? String)?.isEmpty == false })
        else { throw NativeParityFixtureError.invalidFixture }
        var responses: [String: [String: Any]] = [:]
        for (key, value) in rawResponses {
            guard let object = value as? [String: Any] else { throw NativeParityFixtureError.invalidFixture }
            responses[key] = object
        }
        self.fixedNow = date
        localDate = String(fixed.prefix(10))
        sourceSHA256 = sha
        sourceByteLength = byteLength
        self.responses = responses
        self.output = output
        self.selfReview = selfReview
    }

    func response(_ name: String) -> [String: Any] {
        responses[name] ?? [:]
    }
}

private extension SHA256.Digest {
    var hex: String { map { String(format: "%02x", $0) }.joined() }
}
#endif
