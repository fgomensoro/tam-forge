import SwiftUI

struct OrganicSidebar: View {
    let features: Set<NativeFeature>
    let selected: ShellRoute
    let todayRemaining: Int?
    let cardsDue: Int?
    let isRecording: Bool
    let environmentLabel: String
    let statusState: StatusStreamState
    let login: String
    let onSelect: (ShellRoute) -> Void
    let onSignOut: () -> Void

    private struct Item {
        let feature: NativeFeature
        let route: ShellRoute
        let label: String
        let symbol: String
        let identifier: String
    }

    // Existing NativeFeature order; matches the handoff.
    private var items: [Item] {
        [
            Item(feature: .today, route: .today, label: "Today", symbol: "sun.max", identifier: "todayNavigation"),
            Item(feature: .roadmaps, route: .roadmaps, label: "Roadmaps", symbol: "map", identifier: "roadmapsNavigation"),
            Item(feature: .evidence, route: .evidence(activityID: nil), label: "Evidence", symbol: "list.bullet.rectangle", identifier: "evidenceNavigation"),
            Item(feature: .recording, route: .recording, label: "Recording", symbol: "record.circle", identifier: "recordingNavigation"),
            Item(feature: .interviews, route: .interviews, label: "Interviews", symbol: "person.2.wave.2", identifier: "interviewsNavigation"),
            Item(feature: .classes, route: .classes, label: "English classes", symbol: "character.book.closed", identifier: "classesNavigation"),
            Item(feature: .cards, route: .cards, label: "Cards", symbol: "rectangle.on.rectangle.angled", identifier: "cardsNavigation"),
            Item(feature: .progress, route: .progress, label: "Progress", symbol: "chart.line.uptrend.xyaxis", identifier: "progressNavigation"),
        ].filter { features.contains($0.feature) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            brand.padding(.top, Organic.Window.trafficLightInset).padding(.horizontal, Organic.Space.p16)
            VStack(spacing: 2) {
                ForEach(items, id: \.identifier) { row($0) }
            }
            .padding(.top, Organic.Space.p24)
            .padding(.horizontal, Organic.Space.p12)
            Spacer(minLength: 0)
            footer
        }
        .frame(width: 232)
        .background(Organic.Color.sidebarBg)
        .overlay(alignment: .trailing) { Rectangle().fill(Organic.Color.divider).frame(width: 1) }
    }

    private var brand: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(Organic.Color.accent)
                .frame(width: 30, height: 30)
                .overlay {
                    Circle()
                        .fill(Organic.Color.accent2)
                        .frame(width: 12, height: 12)
                        .shadow(color: Organic.Color.neutral900, radius: 0, x: -4, y: 4)
                }
            Text("TAM Forge")
                .font(Organic.Font.figtree(.semibold, size: 18))
                .foregroundStyle(Organic.Color.text)
                .accessibilityIdentifier("shellTitle")
        }
    }

    /// Nav rows stay Buttons: TAMForgeUITests queries app.buttons["<id>Navigation"].
    private func row(_ item: Item) -> some View {
        let isSelected = isSelected(item.route)
        return Button {
            onSelect(item.route)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: item.symbol)
                    .font(.system(size: 17, weight: .bold))
                    .frame(width: 18, height: 18)
                Text(item.label).font(Organic.Font.figtree(.regular, size: 14))
                Spacer(minLength: 0)
                if item.feature == .recording, isRecording {
                    OrganicStatusDot(color: .red, diameter: 8)
                } else if let badge = badge(for: item.feature) {
                    OrganicBadge(text: badge)
                }
            }
            .foregroundStyle(isSelected ? Organic.Color.accent300 : Organic.Color.body)
            .padding(.horizontal, Organic.Space.p12)
            .frame(height: 36)
            .background(isSelected ? Organic.Color.accentOn : .clear, in: Capsule(style: .continuous))
            .contentShape(Capsule(style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(item.identifier)
    }

    /// An open activity keeps Today highlighted, the way the handoff shows it.
    private func isSelected(_ route: ShellRoute) -> Bool {
        switch (selected, route) {
        case (.activity, .today): true
        case (.evidence, .evidence): true
        default: selected == route
        }
    }

    private func badge(for feature: NativeFeature) -> String? {
        switch feature {
        case .today: todayRemaining.flatMap { $0 > 0 ? "\($0) left" : nil }
        case .cards: cardsDue.flatMap { $0 > 0 ? "\($0)" : nil }
        default: nil
        }
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p12) {
            HStack(spacing: Organic.Space.p8) {
                OrganicStatusDot(color: statusDotColor, diameter: 8)
                Text("\(statusLabel) · \(environmentLabel)")
                    .font(Organic.Font.figtree(.regular, size: 12))
                    .foregroundStyle(Organic.Color.muted)
                    .accessibilityIdentifier("environmentLabel")
            }
            HStack(spacing: 10) {
                Circle()
                    .fill(Organic.Color.accent2_700)
                    .frame(width: 28, height: 28)
                    .overlay {
                        Text(String(login.prefix(1)).uppercased())
                            .font(Organic.Font.figtree(.semibold, size: 13))
                            .foregroundStyle(Organic.Color.accent2_100)
                    }
                Text(login).font(Organic.Font.figtree(.regular, size: 13)).foregroundStyle(Organic.Color.body).lineLimit(1)
                Spacer(minLength: 0)
                Button("Sign out") { onSignOut() }
                    .buttonStyle(OrganicGhostButtonStyle())
                    .accessibilityIdentifier("signOutButton")
            }
        }
        .padding(Organic.Space.p16)
        .overlay(alignment: .top) { Rectangle().fill(Organic.Color.divider).frame(height: 1) }
    }

    // StatusStreamState is connecting | live | offline | retrying | unauthorized
    // (Features/Notifications/StatusStreamClient.swift:23). Only `live` is healthy.
    private var statusLabel: String {
        switch statusState {
        case .live: "Updates live"
        case .connecting: "Connecting"
        case .retrying: "Reconnecting"
        case .offline: "Offline"
        case .unauthorized: "Session expired"
        }
    }

    private var statusDotColor: Color {
        switch statusState {
        case .live: Organic.Color.accent2_400
        case .connecting: Organic.Color.muted
        case .retrying, .offline, .unauthorized: Organic.Color.accent300
        }
    }
}
