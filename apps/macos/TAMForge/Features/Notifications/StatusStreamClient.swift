import Foundation

struct StatusEvent: Codable, Equatable, Identifiable, Sendable {
    let id: Int
    let eventType: String
    let aggregateType: String
    let aggregateID: Int
    let subjectID: Int
    let relatedID: Int?
    let occurredAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case eventType = "event_type"
        case aggregateType = "aggregate_type"
        case aggregateID = "aggregate_id"
        case subjectID = "subject_id"
        case relatedID = "related_id"
        case occurredAt = "occurred_at"
    }
}

enum StatusStreamState: Equatable, Sendable {
    case connecting
    case live
    case offline
    case retrying
    case unauthorized
}

struct StatusStreamResponse: Sendable {
    let statusCode: Int
    let contentType: String?
    let chunks: AsyncThrowingStream<Data, Error>
}

protocol StatusStreamTransport: Sendable {
    func open(_ request: URLRequest) async throws -> StatusStreamResponse
}

struct StatusStreamBackoff: Sendable {
    let baseDelay: TimeInterval
    let maximumDelay: TimeInterval

    init(baseDelay: TimeInterval = 1, maximumDelay: TimeInterval = 30) {
        precondition(baseDelay > 0, "baseDelay must be positive")
        precondition(maximumDelay >= baseDelay, "maximumDelay must not be smaller than baseDelay")
        self.baseDelay = baseDelay
        self.maximumDelay = maximumDelay
    }

    func delay(for attempt: Int, random: Double) -> TimeInterval {
        let exponent = min(max(attempt - 1, 0), 8)
        let ceiling = min(maximumDelay, baseDelay * pow(2, Double(exponent)))
        let normalizedRandom = min(max(random, 0), 1)
        return ceiling * (0.5 + (normalizedRandom * 0.5))
    }
}

/// A bearer-authenticated, reconnecting status-event stream. It intentionally retains
/// only event metadata; event bodies and bearer tokens are never logged or persisted.
struct StatusStreamClient: Sendable {
    typealias EventHandler = @Sendable (StatusEvent) async -> Void
    typealias StateHandler = @Sendable (StatusStreamState) async -> Void
    typealias Sleep = @Sendable (TimeInterval) async -> Void
    typealias FallbackPoll = @Sendable () async -> Void

    private let baseURL: URL
    private let bearerToken: @Sendable () async throws -> String
    private let transport: any StatusStreamTransport
    private let backoff: StatusStreamBackoff
    private let sleep: Sleep
    private let fallbackPoll: FallbackPoll
    private let random: @Sendable () -> Double

    init(
        baseURL: URL,
        bearerToken: @escaping @Sendable () async throws -> String,
        transport: any StatusStreamTransport = URLSessionStatusStreamTransport(),
        backoff: StatusStreamBackoff = .init(),
        sleep: @escaping Sleep = { delay in
            let nanoseconds = UInt64(max(delay, 0) * 1_000_000_000)
            try? await Task.sleep(nanoseconds: nanoseconds)
        },
        fallbackPoll: @escaping FallbackPoll = {},
        random: @escaping @Sendable () -> Double = { Double.random(in: 0 ... 1) }
    ) {
        self.baseURL = baseURL
        self.bearerToken = bearerToken
        self.transport = transport
        self.backoff = backoff
        self.sleep = sleep
        self.fallbackPoll = fallbackPoll
        self.random = random
    }

    func run(onEvent: @escaping EventHandler, onState: @escaping StateHandler) async {
        var lastEventID: Int?
        var reconnectAttempt = 0

        while !Task.isCancelled {
            await onState(.connecting)
            let token: String
            do {
                token = try await bearerToken()
            } catch is CancellationError {
                return
            } catch {
                await onState(.unauthorized)
                return
            }

            var request = URLRequest(url: baseURL.appending(path: "/api/v1/events"))
            request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            if let lastEventID {
                request.setValue(String(lastEventID), forHTTPHeaderField: "Last-Event-ID")
            }

            do {
                let response = try await transport.open(request)
                guard response.statusCode != 401 else {
                    await onState(.unauthorized)
                    return
                }
                guard (200 ... 299).contains(response.statusCode),
                      response.contentType?.lowercased().contains("text/event-stream") == true
                else {
                    throw StatusStreamFailure.invalidResponse
                }

                await onState(.live)
                var parser = SSEEventParser()
                for try await chunk in response.chunks {
                    try Task.checkCancellation()
                    for event in parser.append(chunk) where event.id > (lastEventID ?? 0) {
                        lastEventID = event.id
                        reconnectAttempt = 0
                        await onEvent(event)
                    }
                }
            } catch is CancellationError {
                return
            } catch {
                // The UI receives only a safe state; transport details remain local.
            }

            guard !Task.isCancelled else { return }
            await onState(.offline)
            await fallbackPoll()
            guard !Task.isCancelled else { return }

            reconnectAttempt = min(reconnectAttempt + 1, 8)
            await onState(.retrying)
            await sleep(backoff.delay(for: reconnectAttempt, random: random()))
        }
    }
}

struct SSEEventParser {
    static let maximumPendingLineBytes = 64 * 1024
    static let maximumEventDataBytes = 256 * 1024

    private var pending = Data()
    private var eventID: Int?
    private var eventName = "message"
    private var dataLines: [String] = []
    private var eventDataBytes = 0
    private var malformedEvent = false

    mutating func append(_ data: Data) -> [StatusEvent] {
        var events: [StatusEvent] = []
        var index = data.startIndex

        while index < data.endIndex {
            guard let newline = data[index...].firstIndex(of: 0x0A) else {
                let byteCount = data.distance(from: index, to: data.endIndex)
                if byteCount <= Self.maximumPendingLineBytes - pending.count {
                    pending.append(contentsOf: data[index...])
                } else {
                    pending.removeAll(keepingCapacity: false)
                    malformedEvent = true
                }
                break
            }

            let byteCount = data.distance(from: index, to: newline)
            guard byteCount <= Self.maximumPendingLineBytes - pending.count else {
                pending.removeAll(keepingCapacity: false)
                malformedEvent = true
                index = data.index(after: newline)
                continue
            }
            pending.append(contentsOf: data[index..<newline])
            index = data.index(after: newline)

            var line = pending
            pending.removeAll(keepingCapacity: true)
            if line.last == 0x0D { line.removeLast() }
            guard let text = String(data: line, encoding: .utf8) else {
                malformedEvent = true
                continue
            }
            if text.isEmpty {
                if let event = completedEvent() {
                    events.append(event)
                }
                resetEvent()
                continue
            }

            guard !text.hasPrefix(":") else { continue }
            let fieldAndValue = text.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
            let field = String(fieldAndValue[0])
            let value = fieldAndValue.count == 2
                ? String(fieldAndValue[1].drop(while: { $0 == " " }))
                : ""

            switch field {
            case "id":
                guard let id = Int(value), id >= 0 else {
                    malformedEvent = true
                    continue
                }
                eventID = id
            case "event":
                eventName = value
            case "data":
                let appendedBytes = value.utf8.count + (dataLines.isEmpty ? 0 : 1)
                guard !malformedEvent,
                      appendedBytes <= Self.maximumEventDataBytes - eventDataBytes
                else {
                    dataLines.removeAll(keepingCapacity: false)
                    eventDataBytes = 0
                    malformedEvent = true
                    continue
                }
                dataLines.append(value)
                eventDataBytes += appendedBytes
            default:
                continue
            }
        }
        return events
    }

    private func completedEvent() -> StatusEvent? {
        guard !malformedEvent,
              eventName == "status",
              let eventID,
              !dataLines.isEmpty,
              let data = dataLines.joined(separator: "\n").data(using: .utf8),
              let event = try? JSONDecoder().decode(StatusEvent.self, from: data),
              event.id == eventID
        else {
            return nil
        }
        return event
    }

    private mutating func resetEvent() {
        eventID = nil
        eventName = "message"
        dataLines.removeAll(keepingCapacity: true)
        eventDataBytes = 0
        malformedEvent = false
    }
}

private enum StatusStreamFailure: Error {
    case invalidResponse
}

enum StatusStreamSessionConfiguration {
    static func make() -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = .infinity
        return configuration
    }
}

private struct URLSessionStatusStreamTransport: StatusStreamTransport {
    private let session: URLSession

    init(session: URLSession? = nil) {
        if let session {
            self.session = session
            return
        }
        self.session = URLSession(configuration: StatusStreamSessionConfiguration.make())
    }

    func open(_ request: URLRequest) async throws -> StatusStreamResponse {
        let (bytes, response) = try await session.bytes(for: request)
        guard let response = response as? HTTPURLResponse else {
            throw StatusStreamFailure.invalidResponse
        }
        return StatusStreamResponse(
            statusCode: response.statusCode,
            contentType: response.value(forHTTPHeaderField: "Content-Type"),
            chunks: chunks(from: bytes)
        )
    }

    private func chunks(from bytes: URLSession.AsyncBytes) -> AsyncThrowingStream<Data, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var chunk = Data()
                    for try await byte in bytes {
                        try Task.checkCancellation()
                        chunk.append(byte)
                        if chunk.count == 4_096 {
                            continuation.yield(chunk)
                            chunk.removeAll(keepingCapacity: true)
                        }
                    }
                    if !chunk.isEmpty {
                        continuation.yield(chunk)
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
