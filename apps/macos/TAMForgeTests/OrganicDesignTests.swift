import CoreText
import SwiftUI
import XCTest

final class OrganicDesignTests: XCTestCase {
    private func components(_ color: Color) -> (red: Double, green: Double, blue: Double, alpha: Double) {
        let resolved = NSColor(color).usingColorSpace(.sRGB)!
        return (
            Double(resolved.redComponent), Double(resolved.greenComponent),
            Double(resolved.blueComponent), Double(resolved.alphaComponent)
        )
    }

    func testHexInitializerParsesSixDigitValues() {
        let parsed = components(Color(hex: "#c67139"))
        XCTAssertEqual(parsed.red, 198.0 / 255.0, accuracy: 0.001)
        XCTAssertEqual(parsed.green, 113.0 / 255.0, accuracy: 0.001)
        XCTAssertEqual(parsed.blue, 57.0 / 255.0, accuracy: 0.001)
        XCTAssertEqual(parsed.alpha, 1.0, accuracy: 0.001)
    }

    func testHexInitializerAcceptsNoLeadingHash() {
        XCTAssertEqual(components(Color(hex: "2B2620")).red, components(Color(hex: "#2B2620")).red, accuracy: 0.001)
    }

    func testHexInitializerIsCaseInsensitive() {
        XCTAssertEqual(components(Color(hex: "#C67139")).green, components(Color(hex: "#c67139")).green, accuracy: 0.001)
    }

    func testGroundTokensMatchTheHandoff() {
        XCTAssertEqual(components(Organic.Color.bg).red, 43.0 / 255.0, accuracy: 0.001)
        XCTAssertEqual(components(Organic.Color.surface).red, 69.0 / 255.0, accuracy: 0.001)
        XCTAssertEqual(components(Organic.Color.sidebarBg).red, 54.0 / 255.0, accuracy: 0.001)
    }

    func testAccentOnIsAccentAtTwentySixPercent() {
        XCTAssertEqual(components(Organic.Color.accentOn).alpha, 0.26, accuracy: 0.001)
    }

    func testFigtreeWeightsAreRegisteredAndNotSubstituted() {
        // CoreText silently substitutes a fallback when a font is missing, so assert on
        // the resolved PostScript name rather than on the call succeeding. Go through
        // Organic.Font, not a bare CTFontCreateWithName: registration is explicit and
        // happens inside that type, because TAMForgeTests is an unhosted logic-test
        // bundle where ATSApplicationFontsPath is never read.
        for weight in [Organic.Font.Weight.regular, .semibold, .bold] {
            let font = Organic.Font.coreText(weight, size: 16, tabular: false)
            let resolved = CTFontCopyPostScriptName(font) as String
            XCTAssertEqual(
                resolved, weight.rawValue,
                "\(weight.rawValue) was substituted, so it is not bundled or not registered"
            )
        }
    }

    func testTabularFontGivesEveryDigitTheSameAdvance() {
        let font = Organic.Font.coreText(.semibold, size: 20, tabular: true)
        XCTAssertEqual(
            CTFontCopyPostScriptName(font) as String, Organic.Font.Weight.semibold.rawValue,
            "tabular advances mean nothing if the font was substituted"
        )
        let advances = Organic.Font.digitAdvances(in: font)
        XCTAssertEqual(advances.count, 10)
        for advance in advances {
            XCTAssertEqual(advance, advances[0], accuracy: 0.01, "digits are not tabular: \(advances)")
        }
    }

    func testProportionalFontDoesNotForceEqualAdvances() {
        let font = Organic.Font.coreText(.semibold, size: 20, tabular: false)
        let advances = Organic.Font.digitAdvances(in: font)
        XCTAssertFalse(
            advances.allSatisfy { abs($0 - advances[0]) < 0.01 },
            "proportional digits unexpectedly all match, so the tabular test proves nothing"
        )
    }
}
