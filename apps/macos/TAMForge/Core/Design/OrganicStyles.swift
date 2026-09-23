import SwiftUI

// Stage 3 — the content layer. OrganicTokens/Fonts/Components styled the shell;
// this file makes every *feature* view inherit the same look without touching
// its logic. Apply `.organicContentTheme()` once, on `routeDetail` in
// TAMForgeApp.swift. Everything below the shell then gets Figtree, the warm text
// hierarchy (.secondary → muted, .tertiary → faint), card-styled GroupBoxes,
// pill buttons and accent tints.
//
// UI-test contract: Toggles stay native `.checkbox` (tests query
// `app.checkBoxes[...]`) and DisclosureGroups keep the system style (tests query
// `app.disclosureTriangles[...]`). Only tint and font change on those two.

// MARK: - Type roles

enum OrganicText {
    case h1, h2, h3, title, strong, body, small, caption, kicker, mono

    var font: Font {
        switch self {
        case .h1: Organic.Font.figtree(.semibold, size: 28)
        case .h2: Organic.Font.figtree(.semibold, size: 22)
        case .h3: Organic.Font.figtree(.semibold, size: 18)
        case .title: Organic.Font.figtree(.semibold, size: 16)
        case .strong: Organic.Font.figtree(.semibold, size: 14)
        case .body: Organic.Font.figtree(.regular, size: 14)
        case .small: Organic.Font.figtree(.regular, size: 13)
        case .caption: Organic.Font.figtree(.regular, size: 12)
        case .kicker: Organic.Font.figtree(.semibold, size: 11)
        case .mono: .system(size: 12.5, design: .monospaced)
        }
    }

    var tracking: CGFloat {
        switch self {
        case .h1: -0.56
        case .h2: -0.44
        case .h3, .title: -0.18
        case .kicker: 0.9
        default: 0
        }
    }

    var color: Color {
        switch self {
        case .h1, .h2, .h3, .title, .strong: Organic.Color.text
        case .body, .mono: Organic.Color.body
        case .small, .caption, .kicker: Organic.Color.muted
        }
    }
}

extension View {
    /// `Text("Roadmaps").organic(.h1)` — replaces `.font(.largeTitle)` & co.
    func organic(_ role: OrganicText, color: Color? = nil) -> some View {
        font(role.font)
            .tracking(role.tracking)
            .textCase(role == .kicker ? .uppercase : nil)
            .foregroundStyle(color ?? role.color)
    }
}

// MARK: - Semantic status colors (replace .orange / .red / .green)

extension Organic.Color {
    static let warning = accent300
    static let danger = accent300
    static let success = accent2_300
    static let sageOn = accent2.opacity(0.18)
}

// MARK: - GroupBox → card

private struct OrganicGroupDepthKey: EnvironmentKey { static let defaultValue = 0 }

extension EnvironmentValues {
    var organicGroupDepth: Int {
        get { self[OrganicGroupDepthKey.self] }
        set { self[OrganicGroupDepthKey.self] = newValue }
    }
}

/// Top-level GroupBox: `surface` card, r26, title 16 pt semibold.
/// Nested GroupBox: quiet fill (neutral-100 @4 %), r20 — never a card inside a card.
struct OrganicGroupBoxStyle: GroupBoxStyle {
    func makeBody(configuration: Configuration) -> some View {
        OrganicGroupBoxBody(configuration: configuration)
    }
}

private struct OrganicGroupBoxBody: View {
    let configuration: GroupBoxStyleConfiguration
    @Environment(\.organicGroupDepth) private var depth

    var body: some View {
        let nested = depth > 0
        VStack(alignment: .leading, spacing: nested ? Organic.Space.p8 : Organic.Space.p14) {
            configuration.label
                .organic(nested ? .strong : .title)
            configuration.content
                .environment(\.organicGroupDepth, depth + 1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(nested ? Organic.Space.p16 : Organic.Space.p20)
        .background(
            RoundedRectangle(cornerRadius: nested ? Organic.Radius.r20 : Organic.Radius.r26, style: .continuous)
                .fill(nested ? Organic.Color.fill04 : Organic.Color.surface)
        )
    }
}

// MARK: - Buttons: dot-syntax + disabled state

extension ButtonStyle where Self == OrganicPrimaryButtonStyle {
    /// Replaces `.borderedProminent`.
    static var organicPrimary: OrganicPrimaryButtonStyle { .init(size: 14, horizontalPadding: 20, verticalPadding: 10) }
}

extension ButtonStyle where Self == OrganicSecondaryButtonStyle {
    /// The default for every Button under `.organicContentTheme()`.
    static var organicSecondary: OrganicSecondaryButtonStyle { .init() }
}

extension ButtonStyle where Self == OrganicGhostButtonStyle {
    /// Replaces `.link`.
    static var organicLink: OrganicGhostButtonStyle { .init(size: 13, tint: Organic.Color.accent300) }
}

/// The existing button styles have no disabled look. Append
/// `.modifier(OrganicDisabledDimming())` as the last line of makeBody in
/// OrganicPrimary/Secondary/GhostButtonStyle (OrganicComponents.swift) so
/// "Review package" etc. dim to 45 % like the design system specifies.
struct OrganicDisabledDimming: ViewModifier {
    @Environment(\.isEnabled) private var isEnabled
    func body(content: Content) -> some View {
        content.opacity(isEnabled ? 1 : 0.45)
    }
}

// MARK: - Inputs

extension View {
    /// TextField: `.textFieldStyle(.plain).organicField()` — pill, surface fill, hairline.
    func organicField(onSurface: Bool = false) -> some View {
        self
            .textFieldStyle(.plain)
            .font(OrganicText.body.font)
            .foregroundStyle(Organic.Color.text)
            .padding(.horizontal, Organic.Space.p16)
            .padding(.vertical, 10)
            .background(onSurface ? Organic.Color.bg : Organic.Color.surface, in: Capsule(style: .continuous))
            .overlay(Capsule(style: .continuous).strokeBorder(Organic.Color.divider, lineWidth: 1))
    }

    /// TextEditor: `.organicEditor(minHeight: 96)` — r20 field, no system white box.
    func organicEditor(minHeight: CGFloat = 96, monospaced: Bool = false, onSurface: Bool = false) -> some View {
        self
            .scrollContentBackground(.hidden)
            .font(monospaced ? OrganicText.mono.font : OrganicText.body.font)
            .foregroundStyle(Organic.Color.body)
            .lineSpacing(3)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .frame(minHeight: minHeight)
            .background(
                RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous)
                    .fill(onSurface ? Organic.Color.bg : Organic.Color.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous)
                    .strokeBorder(Organic.Color.divider, lineWidth: 1)
            )
    }
}

/// Label above a field — 12 pt muted, 6 pt gap.
struct OrganicFieldLabel<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).organic(.caption)
            content
        }
    }
}

// MARK: - Page header, notice, empty state, metric chip

/// Every route opens with this: kicker, h1, one-line description.
struct OrganicPageHeader<Trailing: View>: View {
    var kicker: String?
    let title: String
    var subtitle: String?
    var titleIdentifier: String?
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .bottom, spacing: Organic.Space.p24) {
            VStack(alignment: .leading, spacing: 6) {
                if let kicker { Text(kicker).organic(.kicker, color: Organic.Color.accent400) }
                Text(title)
                    .organic(.h1)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier(titleIdentifier ?? "")
                if let subtitle {
                    Text(subtitle)
                        .organic(.body, color: Organic.Color.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: 680, alignment: .leading)
                }
            }
            Spacer(minLength: 0)
            trailing
        }
    }
}

extension OrganicPageHeader where Trailing == EmptyView {
    init(kicker: String? = nil, title: String, subtitle: String? = nil, titleIdentifier: String? = nil) {
        self.init(kicker: kicker, title: title, subtitle: subtitle, titleIdentifier: titleIdentifier) { EmptyView() }
    }
}

/// Inline status strip: offline, stale, hard stop, rest day, errors.
struct OrganicNotice<Actions: View>: View {
    let systemImage: String
    var tint: Color = Organic.Color.warning
    var title: String?
    let message: String
    @ViewBuilder var actions: Actions

    var body: some View {
        HStack(alignment: .top, spacing: Organic.Space.p14) {
            Image(systemName: systemImage)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 20)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                if let title { Text(title).organic(.strong) }
                Text(message).organic(.small, color: Organic.Color.neutral300)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            actions
        }
        .padding(.horizontal, Organic.Space.p20)
        .padding(.vertical, Organic.Space.p16)
        .background(tint.opacity(0.12), in: RoundedRectangle(cornerRadius: Organic.Radius.r24, style: .continuous))
    }
}

extension OrganicNotice where Actions == EmptyView {
    init(systemImage: String, tint: Color = Organic.Color.warning, title: String? = nil, message: String) {
        self.init(systemImage: systemImage, tint: tint, title: title, message: message) { EmptyView() }
    }
}

/// Replaces ContentUnavailableView inside the shell.
struct OrganicEmptyState<Actions: View>: View {
    let systemImage: String
    let title: String
    let message: String
    @ViewBuilder var actions: Actions

    var body: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            ZStack {
                Circle().fill(Organic.Color.accentOn)
                Image(systemName: systemImage)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Organic.Color.accent300)
            }
            .frame(width: 52, height: 52)
            Text(title).organic(.h3)
            Text(message).organic(.body, color: Organic.Color.muted)
            actions
        }
        .frame(maxWidth: 460, alignment: .leading)
        .padding(.top, Organic.Space.p40)
    }
}

extension OrganicEmptyState where Actions == EmptyView {
    init(systemImage: String, title: String, message: String) {
        self.init(systemImage: systemImage, title: title, message: message) { EmptyView() }
    }
}

/// "12 tasks", "3 added" — replaces `.background(.quaternary, in: Capsule())` chips.
struct OrganicMetric: View {
    let value: Int
    let label: String
    var tint: Color = Organic.Color.text

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text("\(value)").font(Organic.Font.tabular(.semibold, size: 15)).foregroundStyle(tint)
            Text(label).organic(.caption)
        }
        .padding(.horizontal, Organic.Space.p14)
        .padding(.vertical, 7)
        .background(Organic.Color.fill06, in: Capsule(style: .continuous))
    }
}

/// Section title outside a card ("Required work", "Roadmap versions").
struct OrganicSectionTitle: View {
    let title: String
    var detail: String?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Organic.Space.p12) {
            Text(title).organic(.h3).accessibilityAddTraits(.isHeader)
            if let detail { Text(detail).organic(.small) }
        }
    }
}

// MARK: - Root modifier

extension View {
    /// Apply once, on `routeDetail`.
    func organicContentTheme() -> some View {
        self
            .groupBoxStyle(OrganicGroupBoxStyle())
            .buttonStyle(.organicSecondary)
            .toggleStyle(.checkbox)
            .tint(Organic.Color.accent400)
            .font(OrganicText.body.font)
            .foregroundStyle(Organic.Color.body, Organic.Color.muted, Organic.Color.faint)
            .scrollContentBackground(.hidden)
            .scrollIndicators(.automatic)
    }
}
