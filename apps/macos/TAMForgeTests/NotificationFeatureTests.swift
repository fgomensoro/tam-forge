import Foundation
import XCTest

@MainActor
final class NotificationFeatureTests: XCTestCase {
    func testAllowedNotificationsKeepOnlyPublishedActionTypes() throws {
        let page = try JSONDecoder().decode(NotificationPage.self, from: Data("""
        {"items":[
          {"id":1,"notification_type":"feedback_ready","subject_kind":"activity","subject_id":41,"created_at":"2026-08-27T12:00:00Z","read_at":null},
          {"id":2,"notification_type":"engagement_streak","subject_kind":"activity","subject_id":42,"created_at":"2026-08-27T12:00:00Z","read_at":null}
        ],"next_cursor":null}
        """.utf8))

        XCTAssertEqual(page.allowedItems.map(\.id), [1])
        XCTAssertEqual(page.allowedItems.first?.presentation?.title, "Feedback ready")
    }

    func testIndeterminateReadReconcilesWithServerBeforeOfferingRetry() async {
        let unread = NotificationFixture.item(id: 1, readAt: nil)
        let read = NotificationFixture.item(id: 1, readAt: "2026-08-27T12:05:00Z")
        let client = NotificationClientFixture(
            pages: [.init(items: [unread], nextCursor: nil), .init(items: [read], nextCursor: nil)],
            markReadResult: .failure(URLError(.networkConnectionLost))
        )
        let model = NotificationViewModel(client: client)
        await model.load()

        await model.markRead(id: 1)

        XCTAssertEqual(model.items.first?.readAt, "2026-08-27T12:05:00Z")
        XCTAssertNil(model.actionError)
        let markReadCalls = await client.markReadCalls
        let fetchCount = await client.fetchCount
        XCTAssertEqual(markReadCalls, [1])
        XCTAssertEqual(fetchCount, 2)
    }

    func testStatusInvalidatorDropsDuplicateEventWithoutStoringDomainState() {
        var invalidator = StatusEventInvalidator()
        let event = StatusEvent(
            id: 7,
            eventType: "activity.feedback_ready",
            aggregateType: "activity",
            aggregateID: 41,
            subjectID: 41,
            relatedID: nil,
            occurredAt: "2026-08-27T12:00:00Z"
        )

        XCTAssertTrue(invalidator.consume(event))
        XCTAssertFalse(invalidator.consume(event))
    }
}

private enum NotificationFixture {
    static func item(id: Int, readAt: String?) -> TAMForgeNotification {
        .init(
            id: id,
            notificationType: "feedback_ready",
            subjectKind: "activity",
            subjectID: 41,
            createdAt: "2026-08-27T12:00:00Z",
            readAt: readAt
        )
    }
}

private actor NotificationClientFixture: NotificationServicing {
    enum MarkReadResult: Sendable {
        case success(TAMForgeNotification)
        case failure(URLError)
    }

    private var pages: [NotificationPage]
    private let result: MarkReadResult
    private(set) var fetchCount = 0
    private(set) var markReadCalls: [Int] = []

    init(pages: [NotificationPage], markReadResult: MarkReadResult) {
        self.pages = pages
        result = markReadResult
    }

    func fetchNotifications() async throws -> NotificationPage {
        fetchCount += 1
        return pages.removeFirst()
    }

    func markRead(id: Int) async throws -> TAMForgeNotification {
        markReadCalls.append(id)
        switch result {
        case let .success(item): return item
        case let .failure(error): throw error
        }
    }
}
