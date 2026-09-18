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

        /// Advance width of each digit 0-9, used by the tests to prove `tnum` applied. Shapes
        /// each digit through `CTLine` rather than mapping characters to glyphs directly:
        /// `CTFontGetGlyphsForCharacters` is a raw cmap lookup that never consults the font's
        /// OpenType feature settings, so it cannot see `tnum` substitute a tabular glyph for
        /// the default proportional one. Shaping is what actually applies GSUB features.
        static func digitAdvances(in font: CTFont) -> [Double] {
            "0123456789".map { digit -> Double in
                guard let attributedString = CFAttributedStringCreate(
                    nil, String(digit) as CFString, [kCTFontAttributeName: font] as CFDictionary
                ) else { return 0 }
                let line = CTLineCreateWithAttributedString(attributedString)
                guard let run = (CTLineGetGlyphRuns(line) as? [CTRun])?.first else { return 0 }
                var advance = CGSize.zero
                CTRunGetAdvances(run, CFRange(location: 0, length: 1), &advance)
                return Double(advance.width)
            }
        }

        /// `ATSApplicationFontsPath` in Info.plist only registers fonts for a launched app's
        /// own main bundle. TAMForgeTests has no host application, so its process never
        /// becomes that, and every Figtree lookup would silently substitute. Registering
        /// explicitly from whichever bundle this file was compiled into makes `figtree` and
        /// `coreText` behave the same way in the app and under test.
        private final class BundleToken {}

        private static let registerBundledFontsOnce: Void = {
            let bundle = Bundle(for: BundleToken.self)
            for weight in [Weight.regular, .semibold, .bold] {
                guard let url = bundle.url(forResource: weight.rawValue, withExtension: "ttf") else { continue }
                CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
            }
        }()
    }
}
