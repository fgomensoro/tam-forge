---
name: macos-organic-ui
description: Use when writing or changing any SwiftUI view in apps/macos/TAMForge - adding a screen, a control, a card, a row, a button, a form, an empty state, or restyling an existing one. Carries the Organic design system (colors, type, spacing, radii, primitives), the accessibility-identifier contract the UI tests depend on, and the manual Xcode project wiring every new file needs. Also use when a change mentions tokens, theming, dark mode, Figtree, fonts, or the design handoff.
---

# TAM Forge macOS UI

The Mac app runs on the Organic design system: warm dark ground, terracotta and
sage accents, Figtree type, pill and over-rounded geometry. It is dark-only.

## Pixel authority

`docs/design/macos-organic/README.md` is final for colors, type, spacing, radii
and copy. `docs/design/macos-organic/TAM Forge - Mac.dc.html` is the interactive
reference for all nine routes; open it in a browser and compare against it rather
than against a written description. Neither file is code to port.

The full color ramp is transcribed into `OrganicTokens.swift`, including rungs the
handoff's token list does not spell out. Take values from there, not from the
handoff's prose.

## Never write these

| Instead of | Use |
|---|---|
| `Color(red:green:blue:)`, `Color(hex: "#...")`, `.gray`, `.secondary` | `Organic.Color.*` |
| `.font(.system(size:weight:))`, `.title`, `.headline`, `.caption` | `Organic.Font.figtree(_:size:)` |
| `.monospacedDigit()` on a clock, score or count | `Organic.Font.tabular(_:size:)` |
| A literal corner radius or padding number | `Organic.Radius.*`, `Organic.Space.*` |
| A hand-rolled card, pill, tag or button background | the primitives below |

A number that genuinely has no token (a one-off frame width the handoff
specifies) is fine inline. A *color* never is.

## The primitives

From `TAMForge/Core/Design/OrganicComponents.swift`:

- `.organicCard(radius:padding:shadowed:)` — surface fill and radius; pass `shadowed: true` only for the Today hero card and the Cards flashcard, the only two the handoff shadows
- `.organicFocusRing(_:radius:)` — 2 pt accent ring, offset 2
- `OrganicPrimaryButtonStyle` — accent-400 fill, neutral-900 text
- `OrganicSecondaryButtonStyle` — divider border, subtle fill
- `OrganicGhostButtonStyle` — text only
- `OrganicTag` — the 11 pt rounded tag for blocks, requirements and row states
- `OrganicBadge` — the sidebar count pill
- `OrganicStatusDot` — the status dot

Add a new primitive only when the same construction appears in three places.
Until then it is a modifier or it is inline.

## The identifier contract

184 `accessibilityIdentifier` values exist and 987 lines of
`TAMForgeUITests.swift` depend on them. **Never edit that test file to make a
change pass.** An identifier may move to a different view; it may not be renamed,
dropped, or have its element type changed.

The trap: the UI tests query by element type, for example
`app.buttons["todayNavigation"]`. A row built as an `HStack` with
`.onTapGesture` is not a button in the accessibility tree and breaks every such
assertion. **Interactive rows are `Button` with `.buttonStyle(.plain)`.**

Before claiming a UI change is done:

```bash
git diff --stat origin/main -- apps/macos/TAMForgeUITests/
```

Empty output, or the change is not done.

## Adding a file to the Xcode project

`TAMForge.xcodeproj/project.pbxproj` uses explicit file references, not Xcode 16
synchronized groups. A Swift file that is not wired in does not compile and its
tests do not run, silently. Four edits per file:

1. a `PBXFileReference`
2. `PBXBuildFile` entries — **two** for an app source file, because app sources
   also compile into the unit-test target; **one** for a test file
3. membership in the right `PBXGroup`
4. membership in the build phases: app Sources `A10000000000000000000091`,
   unit-test Sources `A10000000000000000000092`, app Resources
   `A10000000000000000000094`

Then, before building:

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj
```

A malformed project file produces a confusing `xcodebuild` error; the lint says
what is wrong.

## Testing

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation \
  -project apps/macos/TAMForge.xcodeproj -scheme TAMForge \
  -destination 'platform=macOS' test
```

`-only-testing` against a class the project does not contain matches nothing,
runs nothing, and still exits `TEST SUCCEEDED`. Never read that as a pass unless
the output also shows a non-zero test count.
