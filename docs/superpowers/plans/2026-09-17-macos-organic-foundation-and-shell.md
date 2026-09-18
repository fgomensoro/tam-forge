# macOS Organic Redesign: Foundation and Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Organic design layer (tokens, Figtree, primitives, window chrome) and rebuild the app shell on it, without changing a single accessibility identifier.

**Architecture:** Three new files under `TAMForge/Core/Design/` hold every token, primitive and window setting; nothing blends colors at runtime because the handoff already publishes the resolved hex for each `color-mix`. The shell then replaces `NavigationSplitView` with a plain `HStack` over a custom 232 pt sidebar, keeping every route, every `ShellSessionModel.select` call and every identifier where the UI tests expect them.

**Tech Stack:** SwiftUI on macOS, XCTest (the repo has 39 XCTest files and zero Swift Testing files), CoreText for font feature control, a hand-maintained `project.pbxproj`.

**Spec:** `docs/superpowers/specs/2026-09-17-macos-organic-redesign-design.md`

**Design authority:** `docs/design/macos-organic/README.md` for every value, `docs/design/macos-organic/TAM Forge - Mac.dc.html` for the interactive reference.

## Scope of this plan

This plan covers **stages 1 and 2 only** of the eight in the spec: the design
foundation and the shell. Stages 3 through 8 each rewrite a screen on top of the
primitives this plan creates, and each gets its own plan written once its
predecessor has landed. Writing exact SwiftUI for the Today hero card before
`OrganicComponents` exists would produce code against an imagined API, which is
the failure mode this plan is structured to avoid.

Stage 1 lands with no visible change at all. Stage 2 is the first stage a user
can see.

## Global Constraints

- **Identifiers are a contract.** 184 `accessibilityIdentifier` values exist; 987 lines of `TAMForgeUITests.swift` depend on them. An identifier may move to a different view. It may not be renamed, dropped, or have its element type changed. No task in this plan edits `TAMForgeUITests.swift`.
- **Nav rows must stay `Button`s.** The UI tests query `app.buttons["todayNavigation"]` and friends by element type across 29 assertions. Sidebar rows are `Button` with `.buttonStyle(.plain)`, never an `HStack` with `.onTapGesture`.
- **Every new file is three hand edits to `project.pbxproj`** (file reference, build file, group membership) plus one entry per build phase it belongs to. The project uses explicit file references, not synchronized groups.
- **App source files belong to two Sources phases**, the app's and the unit test target's, and therefore need two `PBXBuildFile` entries. This is why `GlobalBanner.swift` appears twice in the build-file section.
- **Reserved pbxproj ID prefix for this work: `D50`.** Verified unused. Existing prefixes are A10 B10 C10 D10 E20 E30 F30 F40 F50 F60 F70 F80 F90 FA0 FB0 FB4 FB5 FC0.
- **Known pbxproj IDs:** app Sources phase `A10000000000000000000091`; unit-test Sources phase `A10000000000000000000092`; app Resources phase `A10000000000000000000094`; `Core` group `A10000000000000000000048`; `TAMForgeTests` group `A10000000000000000000044`.
- **The app is dark-only.** Tokens have no light values. The window pins `.preferredColorScheme(.dark)`.
- **Window sizing:** 1280×820 default, 900×640 hard minimum. Layouts must survive being squeezed below the design width.
- **Build and test command** (matches CI, which runs on `macos-26`):
  ```bash
  xcodebuild -jobs 2 -skipPackagePluginValidation \
    -project apps/macos/TAMForge.xcodeproj -scheme TAMForge \
    -destination 'platform=macOS' test
  ```

## File Structure

| File | Responsibility |
|---|---|
| `TAMForge/Core/Design/OrganicTokens.swift` | Colors, radii, shadows, spacing scale, and the `Color(hex:)` initializer. No views. |
| `TAMForge/Core/Design/OrganicFonts.swift` | Figtree family access and the tabular-figure variant built through CoreText. |
| `TAMForge/Core/Design/OrganicComponents.swift` | The repeated primitives: card, primary/secondary button, tag, pill, focus ring. |
| `TAMForge/Core/Design/OrganicWindow.swift` | Window chrome: hidden title bar, sizing, traffic-light inset. |
| `TAMForge/App/Shell/OrganicSidebar.swift` | The 232 pt sidebar: brand row, nav rows, badges, footer. Takes values, owns no model. |
| `TAMForge/App/Shell/OrganicToolbar.swift` | The 52 pt toolbar: breadcrumb and the notifications pill. |
| `TAMForge/App/Shell/SignInView.swift` | The `signedOut` phase screen. |
| `TAMForge/App/Shell/TodayTaskStatus.swift` | Pure mapping from an activity state string to done/current/ready, plus the "N left" count. Stage 3 reuses it. |
| `TAMForge/Resources/Fonts/` | `Figtree-Regular.ttf`, `Figtree-SemiBold.ttf`, `Figtree-Bold.ttf`, `OFL.txt`. |
| `TAMForgeTests/OrganicDesignTests.swift` | Token parsing, font registration, tabular digits. |
| `TAMForgeTests/TodayTaskStatusTests.swift` | The state mapping and badge count. |

`TAMForge/App/TAMForgeApp.swift` is 649 lines today. Stage 2 pulls the sidebar,
toolbar and sign-in screen out of it rather than growing it further.

---

## Stage 1: Foundation

### Task 1: Color tokens and the hex initializer

**Files:**
- Create: `apps/macos/TAMForge/Core/Design/OrganicTokens.swift`
- Create: `apps/macos/TAMForgeTests/OrganicDesignTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: nothing.
- Produces: `extension Color { init(hex: String) }`; `enum Organic` with nested `Organic.Color`, `Organic.Radius`, `Organic.Space`, `Organic.Shadow`. Every later task and every later stage reads colors from `Organic.Color`.

- [ ] **Step 1: Write the failing test**

Create `apps/macos/TAMForgeTests/OrganicDesignTests.swift`:

```swift
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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test -only-testing:TAMForgeTests/OrganicDesignTests
```

Expected: the build fails because `OrganicDesignTests.swift` is not in the project yet. That is the correct first failure; step 3 adds both the file and the implementation to the project together, because an unreferenced Swift file is invisible to `xcodebuild`.

- [ ] **Step 3: Write the tokens**

Create `apps/macos/TAMForge/Core/Design/OrganicTokens.swift`. Values come from
"Design tokens" in `docs/design/macos-organic/README.md`; the `color-mix`
results are already resolved there, so nothing is blended here.

```swift
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
```

The spec's shadow values are CSS blur radii; SwiftUI's `radius` is roughly half a
CSS blur, which is why 32 becomes 16 and 64 becomes 32.

- [ ] **Step 4: Add both files to `project.pbxproj`**

Four edits, all inside `apps/macos/TAMForge.xcodeproj/project.pbxproj`.

1. In the `PBXFileReference` section, next to the other Core entries:

```
		D50000000000000000000001 /* OrganicTokens.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = OrganicTokens.swift; sourceTree = "<group>"; };
		D50000000000000000000002 /* OrganicDesignTests.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = OrganicDesignTests.swift; sourceTree = "<group>"; };
```

2. In the `PBXBuildFile` section. `OrganicTokens.swift` gets two entries because
app sources also compile into the unit test target:

```
		D50000000000000000000011 /* OrganicTokens.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000001 /* OrganicTokens.swift */; };
		D50000000000000000000012 /* OrganicTokens.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000001 /* OrganicTokens.swift */; };
		D50000000000000000000013 /* OrganicDesignTests.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000002 /* OrganicDesignTests.swift */; };
```

3. Create the `Design` group and hang it off `Core`. Add the group next to the
other `PBXGroup` entries, then add its ID to the `Core` group's children:

```
		D50000000000000000000021 /* Design */ = {
			isa = PBXGroup;
			children = (
				D50000000000000000000001 /* OrganicTokens.swift */,
			);
			path = Design;
			sourceTree = "<group>";
		};
```

In `A10000000000000000000048 /* Core */`, add `D50000000000000000000021 /* Design */,`
to `children`. In `A10000000000000000000044 /* TAMForgeTests */`, add
`D50000000000000000000002 /* OrganicDesignTests.swift */,` to `children`.

4. Add to the build phases: `D50000000000000000000011` to the app Sources phase
`A10000000000000000000091`; `D50000000000000000000012` and
`D50000000000000000000013` to the unit-test Sources phase
`A10000000000000000000092`.

- [ ] **Step 5: Verify the project file is still valid before building**

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj
```

Expected: `OK`. If it reports a syntax error, the edit is malformed; fix it here
rather than reading a confusing `xcodebuild` failure.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test -only-testing:TAMForgeTests/OrganicDesignTests
```

Expected: 5 tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/macos/TAMForge/Core/Design/OrganicTokens.swift apps/macos/TAMForgeTests/OrganicDesignTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(macos): add Organic color, radius, spacing and shadow tokens"
```

---

### Task 2: Vendor Figtree and expose it as a font API

**Files:**
- Create: `apps/macos/TAMForge/Resources/Fonts/Figtree-Regular.ttf`, `Figtree-SemiBold.ttf`, `Figtree-Bold.ttf`, `OFL.txt`
- Create: `apps/macos/TAMForge/Core/Design/OrganicFonts.swift`
- Modify: `apps/macos/TAMForge/Info.plist`
- Modify: `apps/macos/TAMForgeTests/OrganicDesignTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `Organic.Font.figtree(_ weight: Organic.Font.Weight, size: CGFloat) -> Font` and `Organic.Font.tabular(_ weight: Organic.Font.Weight, size: CGFloat) -> Font`, where `Organic.Font.Weight` is `.regular | .semibold | .bold`. Every later task and stage gets type through these two functions and never calls `Font.custom` directly.

- [ ] **Step 1: Vendor the font files**

Figtree is OFL-licensed. The static TTFs come from the upstream project, not the
variable font in `google/fonts`, because a variable font resolves to a single
default instance through `Font.custom` and the three weights would collapse into
one. All four URLs were verified reachable on 2026-09-17.

```bash
mkdir -p apps/macos/TAMForge/Resources/Fonts
for w in Regular SemiBold Bold; do
  curl -sSLf -o "apps/macos/TAMForge/Resources/Fonts/Figtree-$w.ttf" \
    "https://github.com/erikdkennedy/figtree/raw/master/fonts/ttf/Figtree-$w.ttf"
done
curl -sSLf -o apps/macos/TAMForge/Resources/Fonts/OFL.txt \
  "https://github.com/google/fonts/raw/main/ofl/figtree/OFL.txt"
ls -l apps/macos/TAMForge/Resources/Fonts
```

Expected: three TTFs of roughly 57 KB each and a 4.4 KB `OFL.txt`.

- [ ] **Step 2: Write the failing tests**

Append to `apps/macos/TAMForgeTests/OrganicDesignTests.swift`, and add
`import CoreText` at the top of the file:

```swift
    func testFigtreeWeightsAreRegisteredAndNotSubstituted() {
        // CoreText silently substitutes a fallback when a font is missing, so assert
        // on the resolved PostScript name rather than on the call succeeding.
        for name in ["Figtree-Regular", "Figtree-SemiBold", "Figtree-Bold"] {
            let font = CTFontCreateWithName(name as CFString, 16, nil)
            let resolved = CTFontCopyPostScriptName(font) as String
            XCTAssertEqual(resolved, name, "\(name) was substituted, so it is not bundled or not registered")
        }
    }

    func testTabularFontGivesEveryDigitTheSameAdvance() {
        let font = Organic.Font.coreText(.semibold, size: 20, tabular: true)
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
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test -only-testing:TAMForgeTests/OrganicDesignTests
```

Expected: build failure, `Organic.Font` is undefined.

- [ ] **Step 4: Write the font API**

Create `apps/macos/TAMForge/Core/Design/OrganicFonts.swift`. Tabular figures come
from the OpenType `tnum` feature, which Figtree ships (verified with fontTools on
2026-09-17). Applying it through CoreText is deterministic, unlike relying on
`Font.monospacedDigit()` to map onto a custom font's feature table.

```swift
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
            .custom(weight.rawValue, fixedSize: size)
        }

        /// Figtree with OpenType tabular figures, so clocks and scores do not jitter.
        static func tabular(_ weight: Weight, size: CGFloat) -> SwiftUI.Font {
            SwiftUI.Font(coreText(weight, size: size, tabular: true))
        }

        static func coreText(_ weight: Weight, size: CGFloat, tabular: Bool) -> CTFont {
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

        /// Advance width of each digit 0-9, used by the tests to prove `tnum` applied.
        static func digitAdvances(in font: CTFont) -> [Double] {
            "0123456789".unicodeScalars.map { scalar in
                var character = UniChar(scalar.value)
                var glyph = CGGlyph()
                guard CTFontGetGlyphsForCharacters(font, &character, &glyph, 1) else { return 0 }
                return CTFontGetAdvancesForGlyphs(font, .horizontal, &glyph, nil, 1)
            }
        }
    }
}
```

- [ ] **Step 5: Register the fonts in `Info.plist`**

Add this key to `apps/macos/TAMForge/Info.plist`, inside the top-level `<dict>`:

```xml
	<key>ATSApplicationFontsPath</key>
	<string>Fonts</string>
```

`ATSApplicationFontsPath` is relative to the bundle's `Resources` directory, so
the value is `Fonts`, not a full path, and the copy step below must land the
TTFs in `Resources/Fonts`.

- [ ] **Step 6: Add the fonts and the source file to `project.pbxproj`**

File references. Fonts use `sourceTree = "<group>"` inside a new `Fonts` group:

```
		D50000000000000000000003 /* OrganicFonts.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = OrganicFonts.swift; sourceTree = "<group>"; };
		D50000000000000000000004 /* Figtree-Regular.ttf */ = {isa = PBXFileReference; lastKnownFileType = file; path = "Figtree-Regular.ttf"; sourceTree = "<group>"; };
		D50000000000000000000005 /* Figtree-SemiBold.ttf */ = {isa = PBXFileReference; lastKnownFileType = file; path = "Figtree-SemiBold.ttf"; sourceTree = "<group>"; };
		D50000000000000000000006 /* Figtree-Bold.ttf */ = {isa = PBXFileReference; lastKnownFileType = file; path = "Figtree-Bold.ttf"; sourceTree = "<group>"; };
		D50000000000000000000007 /* OFL.txt */ = {isa = PBXFileReference; lastKnownFileType = text; path = OFL.txt; sourceTree = "<group>"; };
```

Build files:

```
		D50000000000000000000014 /* OrganicFonts.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000003 /* OrganicFonts.swift */; };
		D50000000000000000000015 /* OrganicFonts.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000003 /* OrganicFonts.swift */; };
		D50000000000000000000016 /* Figtree-Regular.ttf in Resources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000004 /* Figtree-Regular.ttf */; };
		D50000000000000000000017 /* Figtree-SemiBold.ttf in Resources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000005 /* Figtree-SemiBold.ttf */; };
		D50000000000000000000018 /* Figtree-Bold.ttf in Resources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000006 /* Figtree-Bold.ttf */; };
		D50000000000000000000019 /* OFL.txt in Resources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000007 /* OFL.txt */; };
```

Groups. Add `D50000000000000000000003` to the `Design` group created in Task 1,
and create the `Resources` and `Fonts` groups hanging off the `TAMForge` group:

```
		D50000000000000000000022 /* Resources */ = {
			isa = PBXGroup;
			children = (
				D50000000000000000000023 /* Fonts */,
			);
			path = Resources;
			sourceTree = "<group>";
		};
		D50000000000000000000023 /* Fonts */ = {
			isa = PBXGroup;
			children = (
				D50000000000000000000004 /* Figtree-Regular.ttf */,
				D50000000000000000000005 /* Figtree-SemiBold.ttf */,
				D50000000000000000000006 /* Figtree-Bold.ttf */,
				D50000000000000000000007 /* OFL.txt */,
			);
			path = Fonts;
			sourceTree = "<group>";
		};
```

Build phases: `D50000000000000000000014` into app Sources
`A10000000000000000000091`; `D50000000000000000000015` into unit-test Sources
`A10000000000000000000092`; the four resource build files
(`...16` through `...19`) into the app Resources phase
`A10000000000000000000094`.

The `Fonts` group's `path = Fonts` inside `Resources` is what puts the TTFs at
`Resources/Fonts` in the built bundle, which is what `ATSApplicationFontsPath`
expects.

- [ ] **Step 7: Lint the project file**

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj
```

Expected: `OK`.

- [ ] **Step 8: Run the tests to verify they pass**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test -only-testing:TAMForgeTests/OrganicDesignTests
```

Expected: 8 tests pass. If `testFigtreeWeightsAreRegisteredAndNotSubstituted`
fails, the fonts are in the bundle but not registered: confirm the built app has
`Contents/Resources/Fonts/Figtree-Regular.ttf` with
`find ~/Library/Developer/Xcode/DerivedData -name 'Figtree-Regular.ttf' -path '*TAMForge.app*'`.

- [ ] **Step 9: Commit**

```bash
git add apps/macos/TAMForge/Resources apps/macos/TAMForge/Core/Design/OrganicFonts.swift apps/macos/TAMForge/Info.plist apps/macos/TAMForgeTests/OrganicDesignTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(macos): bundle Figtree and expose it with tabular-figure support"
```

---

### Task 3: The Organic primitives

**Files:**
- Create: `apps/macos/TAMForge/Core/Design/OrganicComponents.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: `Organic.Color`, `Organic.Radius`, `Organic.Space`, `Organic.Shadow` (Task 1); `Organic.Font` (Task 2).
- Produces: `View.organicCard(radius:padding:shadowed:)`, `View.organicFocusRing(_:)`, `OrganicPrimaryButtonStyle`, `OrganicSecondaryButtonStyle`, `OrganicGhostButtonStyle`, `OrganicTag`, `OrganicBadge`, `OrganicStatusDot`. Stages 3 through 8 build every screen out of these.

- [ ] **Step 1: Write the primitives**

There is no test step here. These are pure presentation with no branching logic;
a test asserting a padding value against the same constant it reads would prove
nothing. They are verified by Task 5's build and by Stage 2's screenshots.

Create `apps/macos/TAMForge/Core/Design/OrganicComponents.swift`:

```swift
import SwiftUI

// MARK: - Surfaces

extension View {
    /// The handoff's card: a `surface` fill, a large radius and the lg shadow.
    func organicCard(radius: CGFloat = Organic.Radius.card, padding: CGFloat = Organic.Space.x5, shadowed: Bool = true) -> some View {
        let shadow = Organic.Shadow.large
        return self
            .padding(padding)
            .background(Organic.Color.surface, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .shadow(color: shadowed ? shadow.color : .clear, radius: shadow.radius, x: shadow.x, y: shadow.y)
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
    var verticalPadding: CGFloat = 12

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
            .padding(.horizontal, 16)
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
            .padding(.horizontal, 8)
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
            .padding(.horizontal, 8)
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
```

- [ ] **Step 2: Add the file to `project.pbxproj`**

```
		D50000000000000000000008 /* OrganicComponents.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = OrganicComponents.swift; sourceTree = "<group>"; };
		D5000000000000000000001A /* OrganicComponents.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000008 /* OrganicComponents.swift */; };
		D5000000000000000000001B /* OrganicComponents.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000008 /* OrganicComponents.swift */; };
```

Add `D50000000000000000000008` to the `Design` group, `D5000000000000000000001A`
to app Sources `A10000000000000000000091`, `D5000000000000000000001B` to
unit-test Sources `A10000000000000000000092`.

- [ ] **Step 3: Lint and build**

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj && \
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build
```

Expected: `OK` then `BUILD SUCCEEDED`.

- [ ] **Step 4: Commit**

```bash
git add apps/macos/TAMForge/Core/Design/OrganicComponents.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(macos): add the Organic card, button, tag and badge primitives"
```

---

### Task 4: Window chrome

**Files:**
- Create: `apps/macos/TAMForge/Core/Design/OrganicWindow.swift`
- Modify: `apps/macos/TAMForge/App/TAMForgeApp.swift:30-33` (the `body: some Scene`)
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: `Organic.Color` (Task 1).
- Produces: `Scene.organicWindowChrome()` and the constants `Organic.Window.defaultSize`, `Organic.Window.minimumSize`, `Organic.Window.trafficLightInset`. Stage 2's sidebar reads `trafficLightInset` to clear the traffic lights.

- [ ] **Step 1: Write the window chrome**

Create `apps/macos/TAMForge/Core/Design/OrganicWindow.swift`:

```swift
import SwiftUI

extension Organic {
    enum Window {
        static let defaultSize = CGSize(width: 1280, height: 820)
        /// The shipped minimum stays the hard floor; layouts must survive it.
        static let minimumSize = CGSize(width: 900, height: 640)
        /// Traffic lights sit at y 52, so sidebar content starts below them.
        static let trafficLightInset: CGFloat = 52
    }
}

extension Scene {
    /// Hidden title bar, Organic sizing, dark-only. The palette has no light values.
    func organicWindowChrome() -> some Scene {
        windowStyle(.hiddenTitleBar)
            .defaultSize(width: Organic.Window.defaultSize.width, height: Organic.Window.defaultSize.height)
    }
}
```

- [ ] **Step 2: Apply it to the scene**

In `apps/macos/TAMForge/App/TAMForgeApp.swift`, replace the `body` (currently
lines 30 to 33):

```swift
    var body: some Scene {
        // One workspace owns the authenticated session and its private in-memory drafts.
        Window("TAM Forge", id: "main") {
            NativeShellView(dependencies: dependencies)
                .preferredColorScheme(.dark)
        }
        .organicWindowChrome()
    }
```

- [ ] **Step 3: Widen the frame floor**

In the same file, `NativeSessionView.body` currently ends with
`.frame(minWidth: 900, minHeight: 640)`. Replace that line with the constants so
there is one source of truth:

```swift
        .frame(minWidth: Organic.Window.minimumSize.width, minHeight: Organic.Window.minimumSize.height)
```

Leave the `.padding(24)` on that view alone for now; Stage 2 removes it when the
sidebar takes over the layout.

- [ ] **Step 4: Add the file to `project.pbxproj`**

```
		D50000000000000000000009 /* OrganicWindow.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = OrganicWindow.swift; sourceTree = "<group>"; };
		D5000000000000000000001C /* OrganicWindow.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000009 /* OrganicWindow.swift */; };
		D5000000000000000000001D /* OrganicWindow.swift in Sources */ = {isa = PBXBuildFile; fileRef = D50000000000000000000009 /* OrganicWindow.swift */; };
```

Add `D50000000000000000000009` to the `Design` group, `D5000000000000000000001C`
to app Sources `A10000000000000000000091`, `D5000000000000000000001D` to
unit-test Sources `A10000000000000000000092`.

- [ ] **Step 5: Run the whole suite, including the UI tests**

This is the first task that changes what the app renders, so the identifier
contract gets its first real check.

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj && \
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test
```

Expected: every `TAMForgeTests` and `TAMForgeUITests` test passes with no edit to
`TAMForgeUITests.swift`. A hidden title bar does not change the accessibility
tree, so a UI test failure here means something else broke; stop and report
rather than adjusting the test.

- [ ] **Step 6: Commit**

```bash
git add apps/macos/TAMForge/Core/Design/OrganicWindow.swift apps/macos/TAMForge/App/TAMForgeApp.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(macos): hide the title bar and pin the Organic window sizing"
```

---

### Task 5: Stage 1 gate

- [ ] **Step 1: Confirm the full suite is green**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test 2>&1 | tail -20
```

Expected: `TEST SUCCEEDED`. Paste the real tail into the pull request; do not
claim green without it.

- [ ] **Step 2: Confirm the UI tests were not edited**

```bash
git diff --stat origin/main -- apps/macos/TAMForgeUITests/
```

Expected: empty output. Any change here violates the identifier contract.

- [ ] **Step 3: Open the pull request**

```bash
gh pr create --base main --title "Organic redesign stage 1: design foundation" \
  --body "Tokens, Figtree, primitives and window chrome. No visible change beyond the hidden title bar and the dark-only scheme. Implements stage 1 of docs/superpowers/specs/2026-09-17-macos-organic-redesign-design.md."
```

`gh` is not on `PATH` in this environment; use its absolute path if the bare
command fails.

---

## Stage 2: The shell

Stage 2 starts only after stage 1 has merged. It depends on `Organic.Color`,
`Organic.Font`, the primitives from Task 3 and `Organic.Window` from Task 4.

### Task 6: Task status mapping

**Files:**
- Create: `apps/macos/TAMForge/App/Shell/TodayTaskStatus.swift`
- Create: `apps/macos/TAMForgeTests/TodayTaskStatusTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: `ActivityState` from `Features/Activities/ActivityModels.swift`, `TodayTask` from `Features/Today/TodayFeature.swift`.
- Produces: `enum TodayTaskStatus { case done, current, ready }`, `TodayTaskStatus.init(rawState: String)`, and `TodayTaskStatus.remainingCount(in: [TodayTask]) -> Int`. Stage 2's sidebar reads `remainingCount` for the Today badge; Stage 3 reads the status for the dot color and the line-through in the "Rest of the day" rows.

**Decision this task encodes.** The handoff shows three dot states but never says
which activity states map to which. `TodayTask.state` carries `ActivityState` raw
values. The mapping below treats `needs_work`, `correction_due` and `incomplete`
as work still owed, so they read as `ready`, not `done`. That is a product call
worth confirming before Stage 3 draws line-throughs on top of it.

- [ ] **Step 1: Write the failing test**

Create `apps/macos/TAMForgeTests/TodayTaskStatusTests.swift`:

```swift
import XCTest

final class TodayTaskStatusTests: XCTestCase {
    private func task(_ state: String, order: Int = 1) -> TodayTask {
        TodayTask(
            activityID: order, roadmapOrder: order, stableID: "task-\(order)", block: "deep_work",
            state: state, objective: "Objective \(order)", timeboxMinutes: 35, sourceReferences: [],
            requiredOutput: [], passCriteria: [], allowedAIRole: "none", evidenceRequirements: [],
            required: true, optimisticVersion: 1
        )
    }

    func testInFlightStatesAreCurrent() {
        for state in ["active", "paused", "output_committed"] {
            XCTAssertEqual(TodayTaskStatus(rawState: state), .current, "\(state) should be current")
        }
    }

    func testCompletedStatesAreDone() {
        for state in ["self_review_complete", "ai_processing", "feedback_ready", "demonstrated", "superseded"] {
            XCTAssertEqual(TodayTaskStatus(rawState: state), .done, "\(state) should be done")
        }
    }

    func testStatesThatStillOweWorkAreReady() {
        for state in ["ready", "needs_work", "correction_due", "incomplete"] {
            XCTAssertEqual(TodayTaskStatus(rawState: state), .ready, "\(state) should be ready")
        }
    }

    func testUnknownStateFallsBackToReady() {
        XCTAssertEqual(TodayTaskStatus(rawState: "something_new_from_the_server"), .ready)
    }

    func testRemainingCountExcludesOnlyDoneTasks() {
        let tasks = [
            task("demonstrated", order: 1), task("active", order: 2),
            task("ready", order: 3), task("needs_work", order: 4),
        ]
        XCTAssertEqual(TodayTaskStatus.remainingCount(in: tasks), 3)
    }

    func testRemainingCountIsZeroForAnEmptyDay() {
        XCTAssertEqual(TodayTaskStatus.remainingCount(in: []), 0)
    }
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test -only-testing:TAMForgeTests/TodayTaskStatusTests
```

Expected: build failure, `TodayTaskStatus` is undefined.

- [ ] **Step 3: Write the implementation**

Create `apps/macos/TAMForge/App/Shell/TodayTaskStatus.swift`:

```swift
import Foundation

/// The three row states the Organic Today screen draws. `TodayTask.state` is a raw
/// `ActivityState` string; an unrecognised value from a newer server reads as ready
/// rather than silently disappearing from the count.
enum TodayTaskStatus: Equatable {
    case done
    case current
    case ready

    init(rawState: String) {
        switch ActivityState(rawValue: rawState) {
        case .active, .paused, .outputCommitted:
            self = .current
        case .selfReviewComplete, .aiProcessing, .feedbackReady, .demonstrated, .superseded:
            self = .done
        case .ready, .needsWork, .correctionDue, .incomplete, .none:
            self = .ready
        }
    }

    /// The sidebar's "N left" badge: everything that is not finished.
    static func remainingCount(in tasks: [TodayTask]) -> Int {
        tasks.filter { TodayTaskStatus(rawState: $0.state) != .done }.count
    }
}
```

- [ ] **Step 4: Add both files to `project.pbxproj`**

```
		D5000000000000000000000A /* TodayTaskStatus.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = TodayTaskStatus.swift; sourceTree = "<group>"; };
		D5000000000000000000000B /* TodayTaskStatusTests.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = TodayTaskStatusTests.swift; sourceTree = "<group>"; };
		D5000000000000000000001E /* TodayTaskStatus.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000A /* TodayTaskStatus.swift */; };
		D5000000000000000000001F /* TodayTaskStatus.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000A /* TodayTaskStatus.swift */; };
		D50000000000000000000020 /* TodayTaskStatusTests.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000B /* TodayTaskStatusTests.swift */; };
```

Create the `Shell` group under the existing `App` group:

```
		D50000000000000000000024 /* Shell */ = {
			isa = PBXGroup;
			children = (
				D5000000000000000000000A /* TodayTaskStatus.swift */,
			);
			path = Shell;
			sourceTree = "<group>";
		};
```

Add `D50000000000000000000024` to the `App` group's children,
`D5000000000000000000000B` to the `TAMForgeTests` group
`A10000000000000000000044`, `D5000000000000000000001E` to app Sources
`A10000000000000000000091`, and both `D5000000000000000000001F` and
`D50000000000000000000020` to unit-test Sources `A10000000000000000000092`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj && \
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test -only-testing:TAMForgeTests/TodayTaskStatusTests
```

Expected: 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/macos/TAMForge/App/Shell/TodayTaskStatus.swift apps/macos/TAMForgeTests/TodayTaskStatusTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(macos): map activity states to the Organic task row states"
```

---

### Task 7: The sidebar

**Files:**
- Create: `apps/macos/TAMForge/App/Shell/OrganicSidebar.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: `Organic.Color`, `Organic.Font`, `OrganicBadge`, `OrganicStatusDot`, `Organic.Window.trafficLightInset`, `NativeFeature`, `ShellRoute`.
- Produces: `OrganicSidebar`, initialised with `features: Set<NativeFeature>`, `selected: ShellRoute`, `todayRemaining: Int?`, `cardsDue: Int?`, `isRecording: Bool`, `environmentLabel: String`, `statusState: StatusStreamState`, `login: String`, `onSelect: (ShellRoute) -> Void`, `onSignOut: () -> Void`. It owns no model, so Task 9 can compose it without reaching into `NativeWorkspaceState`.

**Identifier requirements.** Each nav row keeps its identifier and must remain a
`Button`: `todayNavigation`, `roadmapsNavigation`, `evidenceNavigation`,
`recordingNavigation`, `interviewsNavigation`, `classesNavigation`,
`cardsNavigation`, `progressNavigation`. The footer carries `environmentLabel`
and `signOutButton`. Order is Today, Roadmaps, Evidence, Recording, Interviews,
English classes, Cards, Progress, which is the existing `NativeFeature` order and
the handoff's order.

- [ ] **Step 1: Write the sidebar**

Create `apps/macos/TAMForge/App/Shell/OrganicSidebar.swift`. Geometry comes from
the "Shell" section of `docs/design/macos-organic/README.md`: 232 pt wide, 36 pt
rows with radius 999 and 0/12 padding, 10 pt gap, 17 pt icon, 14 pt label.

```swift
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
            brand.padding(.top, Organic.Window.trafficLightInset).padding(.horizontal, Organic.Space.x4)
            VStack(spacing: 2) {
                ForEach(items, id: \.identifier) { row($0) }
            }
            .padding(.top, Organic.Space.x6)
            .padding(.horizontal, Organic.Space.x3)
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
            .padding(.horizontal, Organic.Space.x3)
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
        VStack(alignment: .leading, spacing: Organic.Space.x3) {
            HStack(spacing: Organic.Space.x2) {
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
        .padding(Organic.Space.x4)
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
```

- [ ] **Step 2: Confirm the old connection-status view is gone from the toolbar**

The sidebar footer replaces `NotificationConnectionStatusView`, which Task 9
removes from the detail column. After Task 9, this must return nothing:

```bash
grep -rn 'NotificationConnectionStatusView(' apps/macos/TAMForge/App/
```

Run it now to record the current call site, and again after Task 9 to confirm it
is gone. Leave the view's own definition in place; nothing else needs deleting.

- [ ] **Step 3: Add the file to `project.pbxproj`**

```
		D5000000000000000000000C /* OrganicSidebar.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = OrganicSidebar.swift; sourceTree = "<group>"; };
		D50000000000000000000025 /* OrganicSidebar.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000C /* OrganicSidebar.swift */; };
		D50000000000000000000026 /* OrganicSidebar.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000C /* OrganicSidebar.swift */; };
```

Add `D5000000000000000000000C` to the `Shell` group `D50000000000000000000024`,
`D50000000000000000000025` to app Sources `A10000000000000000000091`,
`D50000000000000000000026` to unit-test Sources `A10000000000000000000092`.

- [ ] **Step 4: Build**

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj && \
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build
```

Expected: `BUILD SUCCEEDED`. The sidebar is not wired into the shell yet, so
nothing renders differently.

- [ ] **Step 5: Commit**

```bash
git add apps/macos/TAMForge/App/Shell/OrganicSidebar.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(macos): add the Organic sidebar"
```

---

### Task 8: Toolbar and sign-in screen

**Files:**
- Create: `apps/macos/TAMForge/App/Shell/OrganicToolbar.swift`
- Create: `apps/macos/TAMForge/App/Shell/SignInView.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: the Stage 1 primitives; `NotificationPanelView` from `Features/Notifications/NotificationView.swift`; `GlobalBannerView` from `Core/Diagnostics/GlobalBanner.swift`.
- Produces: `OrganicToolbar<Trailing: View>(breadcrumb: String, trailing: () -> Trailing)`, a generic over its trailing content so the toolbar never imports a notification type, and `SignInView(environmentLabel: String, banner: GlobalBanner?, onSignIn: () -> Void)`. Task 9 composes both.

**Identifier requirements.** `SignInView` carries `signInButton` (7 references in
the UI tests) and `shellTitle`. `OrganicToolbar` wraps the existing
`NotificationPanelView`, which owns `notificationToggle` and `notificationPanel`
already, so the toolbar adds no identifiers of its own.

- [ ] **Step 1: Write the toolbar**

Create `apps/macos/TAMForge/App/Shell/OrganicToolbar.swift`. 52 pt tall, bottom
hairline, 13 pt breadcrumb on the left in `muted`, notifications pill on the
right.

```swift
import SwiftUI

struct OrganicToolbar<Trailing: View>: View {
    let breadcrumb: String
    @ViewBuilder let trailing: () -> Trailing

    var body: some View {
        HStack(spacing: Organic.Space.x3) {
            Text(breadcrumb)
                .font(Organic.Font.figtree(.regular, size: 13))
                .foregroundStyle(Organic.Color.muted)
                .lineLimit(1)
            Spacer(minLength: Organic.Space.x4)
            trailing()
        }
        .padding(.horizontal, Organic.Space.x9)
        .frame(height: 52)
        .background(Organic.Color.bg)
        .overlay(alignment: .bottom) { Rectangle().fill(Organic.Color.divider).frame(height: 1) }
    }
}
```

The notifications control stays `NotificationPanelView` rather than being
re-implemented, because it owns `notificationToggle` and `notificationPanel` and
the popover behaviour the tests exercise. Restyling its internals is Stage 8's
job; Stage 2 only moves it.

- [ ] **Step 2: Write the sign-in screen**

Create `apps/macos/TAMForge/App/Shell/SignInView.swift`. The handoff's sign-in is
520×400, left-aligned, with the 72 pt icon, the 28 pt title, the primary button
and the PKCE footnote.

```swift
import SwiftUI

struct SignInView: View {
    let environmentLabel: String
    let banner: GlobalBanner?
    let onSignIn: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Organic.Space.x4) {
            Spacer(minLength: 0)
            appIcon
            Text("TAM Forge")
                .font(Organic.Font.figtree(.semibold, size: 28))
                .foregroundStyle(Organic.Color.text)
                .accessibilityIdentifier("shellTitle")
            Text("Sign in to continue your study workspace. \(environmentLabel).")
                .font(Organic.Font.figtree(.regular, size: 14))
                .foregroundStyle(Organic.Color.muted)
                .accessibilityIdentifier("environmentLabel")
            if let banner { GlobalBannerView(banner: banner).organicCard(radius: 24) }
            Button {
                onSignIn()
            } label: {
                HStack(spacing: Organic.Space.x2) {
                    Image(systemName: "chevron.left.forwardslash.chevron.right").font(.system(size: 16, weight: .bold))
                    Text("Sign in with GitHub")
                }
            }
            .buttonStyle(OrganicPrimaryButtonStyle())
            .accessibilityIdentifier("signInButton")
            .keyboardShortcut(.defaultAction)
            Text("PKCE · 15-minute token in memory · refresh token in your Keychain only.")
                .font(Organic.Font.figtree(.regular, size: 12))
                .foregroundStyle(Organic.Color.faint)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 48)
        .padding(.bottom, Organic.Space.x10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(Organic.Color.bg)
    }

    /// Stands in for the real icon until stage 8 adds the asset catalog.
    private var appIcon: some View {
        RoundedRectangle(cornerRadius: 16, style: .continuous)
            .fill(Organic.Color.neutral900)
            .frame(width: 72, height: 72)
            .overlay {
                Circle().fill(Organic.Color.accent).frame(width: 48, height: 48)
                    .overlay(alignment: .center) {
                        Circle().fill(Organic.Color.accent2).frame(width: 27, height: 27).offset(x: -3, y: -3)
                    }
            }
    }
}
```

The GitHub mark has no SF Symbol. `chevron.left.forwardslash.chevron.right` is
the stand-in; stage 8 swaps it when the asset catalog exists. The copy on the
button is unchanged from the handoff, and the button keeps `signInButton`.

- [ ] **Step 3: Add both files to `project.pbxproj`**

```
		D5000000000000000000000D /* OrganicToolbar.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = OrganicToolbar.swift; sourceTree = "<group>"; };
		D5000000000000000000000E /* SignInView.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = SignInView.swift; sourceTree = "<group>"; };
		D50000000000000000000027 /* OrganicToolbar.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000D /* OrganicToolbar.swift */; };
		D50000000000000000000028 /* OrganicToolbar.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000D /* OrganicToolbar.swift */; };
		D50000000000000000000029 /* SignInView.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000E /* SignInView.swift */; };
		D5000000000000000000002A /* SignInView.swift in Sources */ = {isa = PBXBuildFile; fileRef = D5000000000000000000000E /* SignInView.swift */; };
```

Add both file references to the `Shell` group `D50000000000000000000024`;
`D50000000000000000000027` and `D50000000000000000000029` to app Sources
`A10000000000000000000091`; `D50000000000000000000028` and
`D5000000000000000000002A` to unit-test Sources `A10000000000000000000092`.

- [ ] **Step 4: Build**

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj && \
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build
```

Expected: `BUILD SUCCEEDED`.

- [ ] **Step 5: Commit**

```bash
git add apps/macos/TAMForge/App/Shell/OrganicToolbar.swift apps/macos/TAMForge/App/Shell/SignInView.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(macos): add the Organic toolbar and sign-in screen"
```

---

### Task 9: Compose the shell

**Files:**
- Modify: `apps/macos/TAMForge/App/TAMForgeApp.swift` (the `signedOut` case around lines 112-127, and `NativeWorkspaceView.body` around lines 414-486)

**Interfaces:**
- Consumes: `OrganicSidebar`, `OrganicToolbar`, `SignInView`, `TodayTaskStatus.remainingCount`.
- Produces: no new public API. This is the task that makes the redesign visible.

- [ ] **Step 1: Replace the signed-out case**

In `NativeSessionView.body`, the `.signedOut` case is currently a `VStack` with
`shellTitle`, `environmentLabel`, a line of copy, the banner and a "Sign in"
button. Replace the whole case body with:

```swift
            case .signedOut:
                SignInView(
                    environmentLabel: dependencies.environment.displayName,
                    banner: model.banner,
                    onSignIn: { Task { await model.signIn() } }
                )
```

Then remove the `.padding(24)` from the `Group` in that same `body`, because the
sidebar and the page padding now own the layout, and add
`.background(Organic.Color.bg)` in its place.

- [ ] **Step 2: Replace the split view with the sidebar layout**

In `NativeWorkspaceView.body`, replace the entire `NavigationSplitView { ... } detail: { ... }` expression with:

```swift
        HStack(spacing: 0) {
            OrganicSidebar(
                features: dependencies.nativeFeatures,
                selected: session.selectedRoute,
                todayRemaining: state.today.snapshot.map { TodayTaskStatus.remainingCount(in: $0.tasks) },
                cardsDue: state.cards.remaining,
                isRecording: recording.phase.isActive,
                environmentLabel: dependencies.environment.displayName,
                statusState: session.statusState,
                login: loginName,
                onSelect: { session.select($0) },
                onSignOut: signOut
            )
            VStack(spacing: 0) {
                OrganicToolbar(breadcrumb: breadcrumb) {
                    if !dependencies.nativeFeatures.isEmpty {
                        NotificationPanelView(model: state.notifications)
                    }
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: Organic.Space.x6) {
                        if let banner = session.banner { GlobalBannerView(banner: banner).organicCard(radius: 24) }
                        routeDetail
                    }
                    .frame(maxWidth: 1120, alignment: .leading)
                    .padding(.horizontal, Organic.Space.x9)
                    .padding(.top, Organic.Space.x8)
                    .padding(.bottom, Organic.Space.x10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .background(Organic.Color.bg)
        }
```

Keep every modifier that currently hangs off the `NavigationSplitView`
(`.task(id: session.featureRefreshVersion)`, `.onChange(of: session.selectedRoute)`,
`.onDisappear`, and the `.alert`) attached to the new `HStack`. They are
unrelated to the layout and dropping one would silently break refresh, evidence
teardown or the sign-out guard.

- [ ] **Step 3: Add the supporting members**

Still in `NativeWorkspaceView`, add:

```swift
    private var loginName: String {
        if case .signedIn(let login) = session.phase { return login }
        return ""
    }

    private var breadcrumb: String {
        switch session.selectedRoute {
        case .today: "Today"
        case .roadmaps: "Roadmaps"
        case .recording: "Recording"
        case .interviews: "Interviews"
        case .classes: "English classes"
        case .cards: "Cards"
        case .progress: "Progress"
        case .evidence: "Evidence"
        case .activity(let identifier): "Today › Activity \(identifier)"
        }
    }

    private func signOut() {
        if recording.requiresStopBeforeSignOut {
            showRecordingSignOutConfirmation = true
        } else {
            Task {
                await recording.pauseUploadsForSignOut()
                session.signOut()
            }
        }
    }
```

`signOut()` is the body of the existing "Sign out" button moved verbatim, so the
recording guard keeps working.

- [ ] **Step 4: Re-confirm the three properties the sidebar reads**

All three were verified on 2026-09-17: `CardsModel.remaining` (`queue.count`),
`TodayViewModel.snapshot`, and `phase.isActive` on the recording phase, which
`CardsModel.canRecord` already reads as `coordinator.map { !$0.phase.isActive }`.
Re-run the checks in case `main` moved underneath this branch:

```bash
grep -n 'var remaining' apps/macos/TAMForge/Features/Cards/CardsModel.swift
grep -n 'var isActive' apps/macos/TAMForge/Features/Recording/RecordingModels.swift
grep -n 'var snapshot' apps/macos/TAMForge/Features/Today/TodayFeature.swift
```

Expected: one hit each. If any is gone, stop and report rather than adding a new
property to a model to satisfy the sidebar.

- [ ] **Step 5: Run the full suite**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test
```

Expected: every test passes with no edit to `TAMForgeUITests.swift`. The likely
failure is a nav row no longer resolving as `app.buttons[...]`. If that happens,
the fix is in `OrganicSidebar` (the row must be a `Button` with
`.buttonStyle(.plain)`), never in the test.

- [ ] **Step 6: Commit**

```bash
git add apps/macos/TAMForge/App/TAMForgeApp.swift
git commit -m "feat(macos): rebuild the shell on the Organic sidebar and toolbar"
```

---

### Task 10: Stage 2 gate

- [ ] **Step 1: Look at the app**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build
open "$(xcodebuild -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -showBuildSettings 2>/dev/null | awk -F' = ' '/ BUILT_PRODUCTS_DIR/{print $2}' | head -1)/TAM Forge.app"
```

Compare the running shell against section 1 of
`docs/design/macos-organic/TAM Forge - Mac.dc.html`, opened in a browser. Check
the sidebar width, the row pill geometry, the selected-row tint, the badge
placement, the footer, the toolbar hairline and the traffic-light clearance. The
written description is not the check; the reference file is.

- [ ] **Step 2: Check the hard minimum**

Resize the window to 900×640 and confirm the sidebar, toolbar and content column
still lay out without clipping or horizontal scrolling. The handoff keeps 900×640
as the hard floor, so a layout that only works at 1280 is not done.

- [ ] **Step 3: Confirm the UI tests were not edited**

```bash
git diff --stat origin/main -- apps/macos/TAMForgeUITests/
```

Expected: empty output.

- [ ] **Step 4: Confirm the full suite is green and paste the evidence**

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test 2>&1 | tail -20
```

- [ ] **Step 5: Open the pull request**

```bash
gh pr create --base main --title "Organic redesign stage 2: the shell" \
  --body "Custom 232 pt sidebar, 52 pt toolbar and the redesigned sign-in screen, replacing NavigationSplitView. Routes, models and every accessibility identifier are unchanged. Implements stage 2 of docs/superpowers/specs/2026-09-17-macos-organic-redesign-design.md."
```

---

## What this plan does not cover

Stages 3 through 8 from the spec: Today, the bottom bar and the
`ActivityWorkspaceModel` hoist, the Activity workspace, Cards, Progress,
Interviews, English classes, Evidence, Recording, Roadmaps and the app icon. Each
gets its own plan. The bottom bar is the one that needs the most care, because it
is the only stage that changes how a model is owned rather than how it is drawn,
and the spec calls for it to be test-driven against the heartbeat coordinator
before any of it is drawn.
