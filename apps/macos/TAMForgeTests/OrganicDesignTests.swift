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
}
