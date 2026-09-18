import SwiftUI

extension Color {
    /// Parses "#RRGGBB" or "RRGGBB". Invalid input resolves to magenta so a typo is visible, never silent.
    init(hex: String) {
        let digits = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
        guard digits.count == 6, let value = UInt32(digits, radix: 16) else {
            self = Color(.sRGB, red: 1, green: 0, blue: 1, opacity: 1)
            return
        }
        self = Color(
            .sRGB,
            red: Double((value >> 16) & 0xFF) / 255.0,
            green: Double((value >> 8) & 0xFF) / 255.0,
            blue: Double(value & 0xFF) / 255.0,
            opacity: 1
        )
    }
}

enum Organic {
    enum Color {
        // Ground
        static let bg = SwiftUI.Color(hex: "#2B2620")
        static let surface = SwiftUI.Color(hex: "#453B31")
        static let sidebarBg = SwiftUI.Color(hex: "#362C22")

        // Neutrals. The full ramp is transcribed from
        // docs/design/macos-organic/_ds/organic-*/styles.css so later stages never
        // have to guess a rung the handoff's token list happens not to spell out.
        static let text = SwiftUI.Color(hex: "#f9f4ed")        // neutral-100
        static let body = SwiftUI.Color(hex: "#eee7db")        // neutral-200
        static let neutral300 = SwiftUI.Color(hex: "#dcd3c4")
        static let muted = SwiftUI.Color(hex: "#c0b6a5")       // neutral-400
        static let faint = SwiftUI.Color(hex: "#a19786")       // neutral-500
        static let neutral600 = SwiftUI.Color(hex: "#82796a")
        static let neutral700 = SwiftUI.Color(hex: "#645c50")
        static let neutral800 = SwiftUI.Color(hex: "#474238")
        static let neutral900 = SwiftUI.Color(hex: "#2e2b25")

        // Accent (terracotta)
        static let accent = SwiftUI.Color(hex: "#c67139")
        static let accent300 = SwiftUI.Color(hex: "#ffc6a5")
        static let accent400 = SwiftUI.Color(hex: "#f6a06b")
        static let accent500 = SwiftUI.Color(hex: "#d67f48")
        static let accentOn = SwiftUI.Color(hex: "#c67139").opacity(0.26)

        // Accent 2 (sage)
        static let accent2 = SwiftUI.Color(hex: "#7a8a5e")
        static let accent2_100 = SwiftUI.Color(hex: "#f0fae1")
        static let accent2_200 = SwiftUI.Color(hex: "#e1eecc")
        static let accent2_300 = SwiftUI.Color(hex: "#ccdbb2")
        static let accent2_400 = SwiftUI.Color(hex: "#aebf92")
        static let accent2_500 = SwiftUI.Color(hex: "#8fa073")
        static let accent2_600 = SwiftUI.Color(hex: "#728157")
        static let accent2_700 = SwiftUI.Color(hex: "#56633f")
        static let accent2_800 = SwiftUI.Color(hex: "#3d472b")
        static let accent2_900 = SwiftUI.Color(hex: "#272e1b")

        // Hairlines and subtle fills, all neutral-100 at a given alpha
        static let divider = text.opacity(0.11)
        static let fill04 = text.opacity(0.04)
        static let fill06 = text.opacity(0.06)
        static let fill08 = text.opacity(0.08)
        static let fill10 = text.opacity(0.10)
    }

    enum Radius {
        static let pill: CGFloat = 999
        static let window: CGFloat = 14
        static let card: CGFloat = 26
    }

    enum Space {
        static let x1: CGFloat = 4
        static let x2: CGFloat = 8
        static let x3: CGFloat = 12
        static let x4: CGFloat = 16
        static let x5: CGFloat = 20
        static let x6: CGFloat = 24
        static let x7: CGFloat = 28
        static let x8: CGFloat = 32
        static let x9: CGFloat = 36
        static let x10: CGFloat = 40
    }

    enum Shadow {
        /// lg: 0 12px 32px rgba(46,43,37,.22)
        static let large = (color: SwiftUI.Color(hex: "#2e2b25").opacity(0.22), radius: CGFloat(16), x: CGFloat(0), y: CGFloat(12))
        /// window: 0 24px 64px rgba(0,0,0,.55)
        static let window = (color: SwiftUI.Color.black.opacity(0.55), radius: CGFloat(32), x: CGFloat(0), y: CGFloat(24))
    }
}
