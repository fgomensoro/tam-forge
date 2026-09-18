import CoreText
import SwiftUI

extension Organic {
    enum Font {
        enum Weight: String {
            case regular = "Figtree-Regular"
            case semibold = "Figtree-SemiBold"
            case bold = "Figtree-Bold"
        }

        static func figtree(_ weight: Weight, size: CGFloat) -> SwiftUI.Font {
            registerBundledFontsOnce
            return .custom(weight.rawValue, fixedSize: size)
        }

        /// Figtree with OpenType tabular figures, so clocks and scores do not jitter.
        static func tabular(_ weight: Weight, size: CGFloat) -> SwiftUI.Font {
            SwiftUI.Font(coreText(weight, size: size, tabular: true))
        }

        static func coreText(_ weight: Weight, size: CGFloat, tabular: Bool) -> CTFont {
            registerBundledFontsOnce
            let base = CTFontCreateWithName(weight.rawValue as CFString, size, nil)
            guard tabular else { return base }
            let settings: [[CFString: Any]] = [[
                kCTFontFeatureTypeIdentifierKey: kNumberSpacingType,
                kCTFontFeatureSelectorIdentifierKey: kMonospacedNumbersSelector,
            ]]
            let descriptor = CTFontDescriptorCreateWithAttributes(
                [kCTFontFeatureSettingsAttribute: settings] as CFDictionary
            )
            return CTFontCreateCopyWithAttributes(base, size, nil, descriptor)
        }

        /// Registration is explicit on purpose; do not "fix" this by restoring
        /// `ATSApplicationFontsPath` in Info.plist. That key only registers fonts for a
        /// launched app's own main bundle, and TAMForgeTests is an unhosted logic-test
        /// bundle, so its process never becomes that — every Figtree lookup would
        /// silently substitute. It also would not point at anything real: Copy Bundle
        /// Resources flattens the `Fonts` group, so the TTFs land directly in
        /// `Resources/`, not `Resources/Fonts/`. Registering here, from whichever bundle
        /// this file was compiled into, makes `figtree` and `coreText` behave the same
        /// way in the app and under test, with one mechanism instead of two.
        private final class BundleToken {}

        private static let registerBundledFontsOnce: Void = {
            let bundle = Bundle(for: BundleToken.self)
            for weight in [Weight.regular, .semibold, .bold] {
                guard let url = bundle.url(forResource: weight.rawValue, withExtension: "ttf") else {
                    assertionFailure("\(weight.rawValue).ttf is missing from the bundle")
                    continue
                }
                var error: Unmanaged<CFError>?
                if !CTFontManagerRegisterFontsForURL(url as CFURL, .process, &error) {
                    assertionFailure("failed to register \(weight.rawValue): \(error?.takeRetainedValue().localizedDescription ?? "unknown error")")
                }
            }
        }()
    }
}
