import SwiftUI

struct NotificationPanelView: View {
    @ObservedObject var model: NotificationViewModel
    @State private var isPresented = false

    var body: some View {
        Button("Notifications\(model.unreadCount == 0 ? "" : " · \(model.unreadCount)")") {
            isPresented.toggle()
        }
        .accessibilityLabel("Notifications\(model.unreadCount == 0 ? "" : ", \(model.unreadCount) unread")")
        .accessibilityIdentifier("notificationToggle")
        .popover(isPresented: $isPresented) {
            NotificationListView(model: model)
                .frame(minWidth: 360, idealWidth: 420, minHeight: 280)
        }
        .task { await model.load() }
    }
}

struct NotificationConnectionStatusView: View {
    let state: StatusStreamState

    var body: some View {
        Text(label)
            .font(.caption)
            .foregroundStyle(foreground)
            .accessibilityLabel(label)
    }

    private var label: String {
        switch state {
        case .live: "Updates live"
        case .connecting: "Connecting updates"
        case .offline, .retrying: "Updates disconnected · checking periodically"
        case .unauthorized: "Updates need sign-in"
        }
    }

    private var foreground: Color {
        state == .live ? .secondary : .orange
    }
}

private struct NotificationListView: View {
    @ObservedObject var model: NotificationViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Action only").font(.caption).foregroundStyle(.secondary)
            Text("Notifications").font(.title2).bold().accessibilityAddTraits(.isHeader)
            content
            Text("Only feedback, corrections, interviews, Saturday assessments, and failures requiring action appear here.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .accessibilityIdentifier("notificationPanel")
    }

    @ViewBuilder
    private var content: some View {
        switch model.state {
        case .loading:
            ProgressView("Loading notifications…").accessibilityLabel("Loading notifications")
        case .empty:
            Text("Nothing needs your attention.")
        case let .content(page), let .partial(page), let .stale(page):
            notificationItems(
                page.allowedItems,
                defaultActionNotificationID: page.defaultActionNotificationID,
                stale: isStale
            )
        case let .offline(page):
            if let page {
                notificationItems(
                    page.allowedItems,
                    defaultActionNotificationID: page.defaultActionNotificationID,
                    stale: true
                )
            }
            else { problem("Notifications are offline. Study can continue independently.") }
        case let .problem(page):
            if let page {
                notificationItems(
                    page.allowedItems,
                    defaultActionNotificationID: page.defaultActionNotificationID,
                    stale: true
                )
            }
            else { problem("Notifications are unavailable. Study can continue independently.") }
        }
    }

    private var isStale: Bool {
        if case .stale = model.state { return true }
        return false
    }

    private func problem(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(message).foregroundStyle(.red)
            Button("Retry") { Task { await model.retry() } }
                .accessibilityIdentifier("notificationRetryButton")
        }
    }

    private func notificationItems(
        _ items: [TAMForgeNotification],
        defaultActionNotificationID: Int?,
        stale: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if stale { Text("Showing last available notifications").font(.caption).foregroundStyle(.orange) }
            if items.isEmpty {
                Text("Nothing needs your attention.")
            } else {
                ForEach(items) { item in
                    if let presentation = item.presentation {
                        HStack(alignment: .top, spacing: 12) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(presentation.title).bold()
                                Text(presentation.detail).font(.subheadline).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if item.readAt == nil {
                                Button(model.pendingReadIDs.contains(item.id) ? "Checking…" : "Mark read") {
                                    Task { await model.markRead(id: item.id) }
                                }
                                .disabled(model.pendingReadIDs.contains(item.id))
                                .accessibilityLabel("Mark \(presentation.title) as read")
                                .notificationDefaultAction(
                                    item.id == defaultActionNotificationID
                                )
                            }
                        }
                        .padding(.vertical, 4)
                        .accessibilityElement(children: .contain)
                    }
                }
            }
            if let error = model.actionError { Text(error).font(.caption).foregroundStyle(.orange) }
        }
    }
}

private extension View {
    @ViewBuilder
    func notificationDefaultAction(_ enabled: Bool) -> some View {
        if enabled { keyboardShortcut(.defaultAction) }
        else { self }
    }
}
