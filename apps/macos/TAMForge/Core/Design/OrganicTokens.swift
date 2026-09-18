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
        static let accent100 = SwiftUI.Color(hex: "#fff2eb")
        static let accent200 = SwiftUI.Color(hex: "#ffe1d0")
        static let accent300 = SwiftUI.Color(hex: "#ffc6a5")
        static let accent400 = SwiftUI.Color(hex: "#f6a06b")
        static let accent500 = SwiftUI.Color(hex: "#d67f48")
        static let accent600 = SwiftUI.Color(hex: "#b2622d")
        static let accent700 = SwiftUI.Color(hex: "#8c491a")
        static let accent800 = SwiftUI.Color(hex: "#643312")
        static let accent900 = SwiftUI.Color(hex: "#402310")
        static let accentOn = accent.opacity(0.26)

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

    /// The handoff's radius scale. Cards are named by value, not semantically,
    /// because the handoff specifies eight card sizes (36/32/30/28/26/24/22/20).
    /// There is no single "card radius", and a semantic name invites shipping 26
    /// where the design says 32.
    enum Radius {
        static let pill: CGFloat = 999
        static let r20: CGFloat = 20
        static let r22: CGFloat = 22
        static let r24: CGFloat = 24
        static let r26: CGFloat = 26
        static let r28: CGFloat = 28
        static let r30: CGFloat = 30
        static let r32: CGFloat = 32
        static let r36: CGFloat = 36
    }

    /// The handoff's 12-rung spacing scale. Named by value, never by ordinal,
    /// so `p16` cannot be misread as 16 rungs or as 4 pt.
    enum Space {
        static let p4: CGFloat = 4
        static let p8: CGFloat = 8
        static let p12: CGFloat = 12
        static let p14: CGFloat = 14
        static let p16: CGFloat = 16
        static let p18: CGFloat = 18
        static let p20: CGFloat = 20
        static let p24: CGFloat = 24
        static let p28: CGFloat = 28
        static let p32: CGFloat = 32
        static let p36: CGFloat = 36
        static let p40: CGFloat = 40
    }

    enum Shadow {
        /// Handoff lg: `0 12px 32px rgba(46,43,37,.22)`. SwiftUI's radius is about
        /// half a CSS blur, so 32px blur becomes radius 16.
        static let large = (color: SwiftUI.Color(hex: "#2e2b25").opacity(0.22), radius: CGFloat(16), x: CGFloat(0), y: CGFloat(12))
    }
}
