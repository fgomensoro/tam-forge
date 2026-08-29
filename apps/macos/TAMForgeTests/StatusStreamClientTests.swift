import Foundation
import XCTest

final class StatusStreamClientTests: XCTestCase {
    func testParserHandlesPartialUTF8AndDropsMalformedEvents() {
        var parser = SSEEventParser()
        let payload = Data(statusBlock(id: 4, eventType: "processing_é").utf8)
        let split = try! XCTUnwrap(payload.firstIndex(of: 0xC3))

        XCTAssertTrue(parser.append(Data(payload.prefix(through: split))).isEmpty)
        XCTAssertEqual(parser.append(Data(payload.suffix(from: payload.index(after: split)))).map(\.id), [4])
        XCTAssertTrue(parser.append(Data("id: invalid\ndata: not-json\n\n".utf8)).isEmpty)
    }

    func testParserDropsEventWhenSSEAndPayloadIdentifiersDisagree() {
        var parser = SSEEventParser()

        let events = parser.append(Data(statusBlock(id: 4, payloadID: 5).utf8))

        XCTAssertTrue(events.isEmpty)
    }

    func testParserBoundsNoNewlineInputThenRecoversAtEventBoundary() {
        var parser = SSEEventParser()

        XCTAssertTrue(
            parser.append(
                Data(repeating: 0x61, count: SSEEventParser.maximumPendingLineBytes + 1)
            ).isEmpty
        )
        XCTAssertTrue(parser.append(Data("\n".utf8)).isEmpty)

        XCTAssertEqual(parser.append(Data(statusBlock(id: 9).utf8)).map(\.id), [9])
    }

    func testParserBoundsOversizedMultiLineEventThenRecoversAtEventBoundary() {
        var parser = SSEEventParser()
        let dataLine = String(repeating: "x", count: SSEEventParser.maximumEventDataBytes / 2)
        let oversized = "id: 1\nevent: status\ndata: \(dataLine)\ndata: \(dataLine)\n\n"

        XCTAssertTrue(parser.append(Data(oversized.utf8)).isEmpty)
        XCTAssertEqual(parser.append(Data(statusBlock(id: 10).utf8)).map(\.id), [10])
    }

    func testReconnectsWithLastEventIDSuppressesDuplicatesAndPollsFallback() async {
        let transport = FixtureStatusStreamTransport(outcomes: [
            .response(statusCode: 200, chunks: [Data(statusBlock(id: 7).utf8)], remainsOpen: false),
            .response(
                statusCode: 200,
                chunks: [Data((statusBlock(id: 7) + statusBlock(id: 8)).utf8)],
                remainsOpen: true
            ),
        ])
        let recorder = StatusStreamRecorder()
        let client = StatusStreamClient(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { "native-test-token" },
            transport: transport,
            backoff: .init(baseDelay: 0.01, maximumDelay: 0.02),
            sleep: { _ in await Task.yield() },
            fallbackPoll: { await recorder.recordPoll() }
        )

        let task = Task {
            await client.run(
                onEvent: { await recorder.record($0) },
                onState: { await recorder.record($0) }
            )
        }
        let receivedExpectedEvents = await recorder.waitForEventCount(2)
        XCTAssertTrue(receivedExpectedEvents)
        task.cancel()
        await task.value

        let requests = await transport.requests
        let events = await recorder.events
        XCTAssertEqual(events.map(\.id), [7, 8])
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests[0].value(forHTTPHeaderField: "Authorization"), "Bearer native-test-token")
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "Last-Event-ID"), "7")
        let pollCount = await recorder.pollCount
        XCTAssertEqual(pollCount, 1)
    }

    func testUnauthorizedStopsWithoutReconnect() async {
        let transport = FixtureStatusStreamTransport(outcomes: [
            .response(statusCode: 401, chunks: [], remainsOpen: false),
        ])
        let recorder = StatusStreamRecorder()
        let client = StatusStreamClient(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { "native-test-token" },
            transport: transport,
            sleep: { _ in await Task.yield() }
        )

        await client.run(
            onEvent: { await recorder.record($0) },
            onState: { await recorder.record($0) }
        )

        let requests = await transport.requests
        let states = await recorder.states
        XCTAssertEqual(requests.count, 1)
        XCTAssertEqual(states.last, .unauthorized)
    }

    func testCancellationStopsAnOpenStreamWithoutReconnect() async {
        let transport = FixtureStatusStreamTransport(outcomes: [
            .response(statusCode: 200, chunks: [], remainsOpen: true),
        ])
        let client = StatusStreamClient(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { "native-test-token" },
            transport: transport,
            sleep: { _ in await Task.yield() }
        )

        let task = Task { await client.run(onEvent: { _ in }, onState: { _ in }) }
        let openedStream = await transport.waitForRequestCount(1)
        XCTAssertTrue(openedStream)
        task.cancel()
        await task.value
        await Task.yield()

        let requests = await transport.requests
        XCTAssertEqual(requests.count, 1)
    }

    func testBackoffIsBoundedAndJittered() {
        let backoff = StatusStreamBackoff(baseDelay: 1, maximumDelay: 8)

        XCTAssertLessThan(backoff.delay(for: 1, random: 0), backoff.delay(for: 1, random: 1))
        XCTAssertLessThanOrEqual(backoff.delay(for: 50, random: 1), 8)
    }
}

private func statusBlock(
    id: Int,
    payloadID: Int? = nil,
    eventType: String = "processing"
) -> String {
    """
    id: \(id)
    event: status
    data: {"id":\(payloadID ?? id),"event_type":"\(eventType)","aggregate_type":"activity","aggregate_id":9,"subject_id":9,"related_id":null,"occurred_at":"2026-08-28T00:00:00Z"}


    """
}

private actor StatusStreamRecorder {
    private(set) var events: [StatusEvent] = []
    private(set) var states: [StatusStreamState] = []
    private(set) var pollCount = 0

    func record(_ event: StatusEvent) { events.append(event) }
    func record(_ state: StatusStreamState) { states.append(state) }
    func recordPoll() { pollCount += 1 }

    func waitForEventCount(_ expected: Int) async -> Bool {
        for _ in 0 ..< 10_000 {
            if events.count >= expected { return true }
            await Task.yield()
        }
        return false
    }
}

private actor FixtureStatusStreamTransport: StatusStreamTransport {
    enum Outcome: Sendable {
        case response(statusCode: Int, chunks: [Data], remainsOpen: Bool)
    }

    private var outcomes: [Outcome]
    private(set) var requests: [URLRequest] = []

    init(outcomes: [Outcome]) {
        self.outcomes = outcomes
    }

    func open(_ request: URLRequest) async throws -> StatusStreamResponse {
        requests.append(request)
        let outcome = outcomes.removeFirst()
        switch outcome {
        case let .response(statusCode, chunks, remainsOpen):
            return StatusStreamResponse(
                statusCode: statusCode,
                contentType: "text/event-stream",
                chunks: AsyncThrowingStream { continuation in
                    for chunk in chunks { continuation.yield(chunk) }
                    if !remainsOpen { continuation.finish() }
                }
            )
        }
    }

    func waitForRequestCount(_ expected: Int) async -> Bool {
        for _ in 0 ..< 10_000 {
            if requests.count >= expected { return true }
            await Task.yield()
        }
        return false
    }
}
