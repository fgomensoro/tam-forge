import Combine
import Foundation
import HTTPTypes

struct TAMForgeNotification: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let notificationType: String
    let subjectKind: String
    let subjectID: Int
    let createdAt: String
    let readAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case notificationType = "notification_type"
        case subjectKind = "subject_kind"
        case subjectID = "subject_id"
        case createdAt = "created_at"
        case readAt = "read_at"
    }

    var presentation: NotificationPresentation? {
        NotificationPresentation(notificationType: notificationType)
    }
}

struct NotificationPage: Codable, Equatable, Sendable {
    let items: [TAMForgeNotification]
    let nextCursor: Int?

    enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
    }

    var allowedItems: [TAMForgeNotification] {
        items.filter { $0.presentation != nil }
    }
}

struct NotificationPresentation: Equatable, Sendable {
    let title: String
    let detail: String

    init?(notificationType: String) {
        switch notificationType {
        case "feedback_ready":
            title = "Feedback ready"
            detail = "Your asynchronous review is ready."
        case "correction_due":
            title = "Correction due"
            detail = "One planned correction is ready for its assigned slot."
        case "upcoming_real_interview":
            title = "Upcoming real interview"
            detail = "Review the interview plan without adding extra study time."
        case "saturday_assessment":
            title = "Saturday assessment"
            detail = "Your no-AI assessment is ready within the 120-minute limit."
        case "processing_failure_requires_action":
            title = "Processing needs action"
            detail = "Study can continue independently. Your source evidence remains saved."
        default:
            return nil
        }
    }
}

protocol NotificationServicing: Sendable {
    func fetchNotifications() async throws -> NotificationPage
    func markRead(id: Int) async throws -> TAMForgeNotification
}

struct NativeNotificationAPIClient: NotificationServicing {
    let transport: NativeAPITransport

    func fetchNotifications() async throws -> NotificationPage {
        let response = try await transport.send(
            .init(method: .get, path: "/api/v1/notifications?limit=100")
        )
        let page = try response.decoded(as: Components.Schemas.NotificationPage.self)
        return NotificationPage(items: page.items.map(TAMForgeNotification.init(api:)), nextCursor: page.nextCursor)
    }

    func markRead(id: Int) async throws -> TAMForgeNotification {
        let response = try await transport.send(
            .init(method: .post, path: "/api/v1/notifications/\(id)/read")
        )
        return TAMForgeNotification(api: try response.decoded(as: Components.Schemas.NotificationResponse.self))
    }
}

private extension TAMForgeNotification {
    init(api: Components.Schemas.NotificationResponse) {
        self.init(
            id: api.id, notificationType: api.notificationType.rawValue,
            subjectKind: api.subjectKind.rawValue, subjectID: api.subjectId,
            createdAt: NativeJSONCodec.timestamp(api.createdAt),
            readAt: api.readAt.map(NativeJSONCodec.timestamp)
        )
    }
}

enum NotificationLoadState: Equatable {
    case loading
    case content(NotificationPage)
    case empty
    case partial(NotificationPage)
    case stale(NotificationPage)
    case offline(NotificationPage?)
    case problem(NotificationPage?)

    var page: NotificationPage? {
        switch self {
        case let .content(page), let .partial(page), let .stale(page): page
        case let .offline(page), let .problem(page): page
        case .loading, .empty: nil
        }
    }
}

struct StatusEventInvalidator: Equatable, Sendable {
    private(set) var latestEventID = 0

    mutating func consume(_ event: StatusEvent) -> Bool {
        guard event.id > latestEventID else { return false }
        latestEventID = event.id
        return true
    }
}

@MainActor
final class NotificationViewModel: ObservableObject {
    @Published private(set) var state: NotificationLoadState = .loading
    @Published private(set) var actionError: String?
    @Published private(set) var pendingReadIDs: Set<Int> = []

    private let client: any NotificationServicing
    private var invalidator = StatusEventInvalidator()

    init(client: any NotificationServicing) {
        self.client = client
    }

    var items: [TAMForgeNotification] { state.page?.allowedItems ?? [] }
    var unreadCount: Int { items.filter { $0.readAt == nil }.count }

    func load() async {
        let previous = state.page
        if previous == nil { state = .loading }
        do {
            let page = try await client.fetchNotifications()
            state = Self.presentationState(for: page)
        } catch is CancellationError {
            return
        } catch {
            state = Self.failureState(for: error, previous: previous)
        }
    }

    func retry() async {
        await load()
    }

    func markRead(id: Int) async {
        guard let item = items.first(where: { $0.id == id }), item.readAt == nil,
              !pendingReadIDs.contains(id)
        else { return }
        pendingReadIDs.insert(id)
        actionError = nil
        defer { pendingReadIDs.remove(id) }
        do {
            let saved = try await client.markRead(id: id)
            replace(saved)
        } catch is CancellationError {
            return
        } catch {
            await load()
            if items.first(where: { $0.id == id })?.readAt == nil {
                actionError = "We could not confirm this notification. Retry when updates reconnect."
            }
        }
    }

    func receive(_ event: StatusEvent) {
        guard invalidator.consume(event) else { return }
        Task { [weak self] in await self?.load() }
    }

    private func replace(_ saved: TAMForgeNotification) {
        guard let page = state.page else { return }
        let items = page.items.map { $0.id == saved.id ? saved : $0 }
        state = Self.presentationState(for: .init(items: items, nextCursor: page.nextCursor))
    }

    private static func presentationState(for page: NotificationPage) -> NotificationLoadState {
        let allowed = page.allowedItems
        if allowed.isEmpty { return page.items.isEmpty ? .empty : .partial(page) }
        return .content(page)
    }

    private static func failureState(for error: Error, previous: NotificationPage?) -> NotificationLoadState {
        if error is URLError { return .offline(previous) }
        if let previous { return .stale(previous) }
        return .problem(nil)
    }
}
