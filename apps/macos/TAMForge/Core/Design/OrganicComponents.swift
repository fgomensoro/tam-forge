import SwiftUI

// MARK: - Surfaces

extension View {
    /// The handoff's card: a `surface` fill and a large radius. The shadow is opt-in
    /// because only two surfaces in the whole handoff call for it (the Today hero card
    /// and the Cards flashcard); every other card specifies a radius and a fill only.
    /// It is applied to the fill shape, not chained after the background, so a card
    /// nested in another card does not re-blur the inner card's shadow into a halo.
    func organicCard(radius: CGFloat = Organic.Radius.r26, padding: CGFloat = Organic.Space.p20, shadowed: Bool = false) -> some View {
        let shadow = Organic.Shadow.large
        return self
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(Organic.Color.surface)
                    .shadow(color: shadowed ? shadow.color : .clear, radius: shadow.radius, x: shadow.x, y: shadow.y)
            )
    }

    /// Focus ring: 2 pt accent, offset 2.
    func organicFocusRing(_ isFocused: Bool, radius: CGFloat = Organic.Radius.pill) -> some View {
        overlay(
            RoundedRectangle(cornerRadius: radius, style: .continuous)
                .strokeBorder(isFocused ? Organic.Color.accent : .clear, lineWidth: 2)
                .padding(-2)
        )
    }
}

// MARK: - Buttons

struct OrganicPrimaryButtonStyle: ButtonStyle {
    var size: CGFloat = 15
    var horizontalPadding: CGFloat = 22
    var verticalPadding: CGFloat = Organic.Space.p12

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Organic.Font.figtree(.semibold, size: size))
            .foregroundStyle(Organic.Color.neutral900)
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, verticalPadding)
            .background(
                configuration.isPressed ? Organic.Color.accent500 : Organic.Color.accent400,
                in: Capsule(style: .continuous)
            )
            .contentShape(Capsule(style: .continuous))
    }
}

struct OrganicSecondaryButtonStyle: ButtonStyle {
    var size: CGFloat = 13

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Organic.Font.figtree(.semibold, size: size))
            .foregroundStyle(Organic.Color.body)
            .padding(.horizontal, Organic.Space.p16)
            .padding(.vertical, 9)
            .background(configuration.isPressed ? Organic.Color.fill08 : Organic.Color.fill04, in: Capsule(style: .continuous))
            .overlay(Capsule(style: .continuous).strokeBorder(Organic.Color.divider, lineWidth: 1))
            .contentShape(Capsule(style: .continuous))
    }
}

struct OrganicGhostButtonStyle: ButtonStyle {
    var size: CGFloat = 12
    var tint: Color = Organic.Color.muted

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Organic.Font.figtree(.semibold, size: size))
            .foregroundStyle(configuration.isPressed ? Organic.Color.text : tint)
            .contentShape(Rectangle())
    }
}

// MARK: - Small parts

/// The 11 pt rounded tag used for blocks, requirements and row states.
struct OrganicTag: View {
    let text: String
    var background: Color = Organic.Color.fill08
    var foreground: Color = Organic.Color.neutral300

    var body: some View {
        Text(text)
            .font(Organic.Font.figtree(.semibold, size: 11))
            .foregroundStyle(foreground)
            .padding(.horizontal, Organic.Space.p8)
            .padding(.vertical, 3)
            .background(background, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

/// The sidebar count pill: accent at 26 %, accent-300 text.
struct OrganicBadge: View {
    let text: String

    var body: some View {
        Text(text)
            .font(Organic.Font.figtree(.regular, size: 11))
            .foregroundStyle(Organic.Color.accent300)
            .padding(.horizontal, Organic.Space.p8)
            .padding(.vertical, 1)
            .background(Organic.Color.accentOn, in: Capsule(style: .continuous))
    }
}

/// The 9 pt dot in front of a task row, and the 8 pt one in the sidebar footer.
struct OrganicStatusDot: View {
    let color: Color
    var diameter: CGFloat = 9

    var body: some View {
        Circle().fill(color).frame(width: diameter, height: diameter)
    }
}
