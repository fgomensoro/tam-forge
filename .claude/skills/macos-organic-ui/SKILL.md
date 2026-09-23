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
reference for all nine routes, and its inline styles are where the geometry numbers
come from. Compare against it rather than against a written description, and for
anything with a position or a size compare measured numbers rather than an
impression: see "Measuring against the handoff" below. Neither file is code to port.

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

A number that genuinely has no token is fine inline — the handoff states a spacing
scale of twelve rungs and a radius scale of ten, and values outside those, like the
primary button's 22 pt horizontal padding or a one-off frame width, are meant to be
literal. A **color** never is.

Radius has no single "card" token on purpose: the handoff gives eight card sizes.
Check the handoff for the surface you are building and pass that radius explicitly —
`.organicCard(radius: Organic.Radius.r32)` for the Today hero card, `r36` for the
Cards flashcard. Taking the default because it is there is how a card ships at the
wrong size while looking like it followed the rules.

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

A second trap: on macOS a `Text`'s accessibility **value** is the string as
rendered, and `app.staticTexts["Before"]` matches it. `.organic(.kicker)` and any
`.textCase(.uppercase)` render "BEFORE", which no longer matches, and an
`.accessibilityLabel` does not change the value. A string the tests look up stays
mixed case; grep the test file before putting a visible string in the kicker role.

Before claiming a UI change is done:

```bash
git diff --stat origin/main -- apps/macos/TAMForgeUITests/
```

Empty output, or the change is not done.

## Scroll content is eager

Build the content of a `ScrollView` out of plain `VStack` and `HStack`. **Never
`LazyVStack`, `LazyHStack` or `LazyVGrid`.**

A lazy stack sizes the rows it has not realized by estimate, so the scroll view's
content height, and with it the end of its scroll range, moves as rows realize.
Anything below the fold stops being reachable: `RoadmapAdministrationView`'s four
semantic-diff sections ran the estimate about 1,400 pt short on a ~10,500 pt page,
and the approval gate under them could not be scrolled into the viewport at all,
by `testNativeFoundationParityJourney` or by a person. That breaks the identifier
contract above as surely as a rename does, since an identifier that can never be
revealed fails the same assertions as one that was dropped.

The exception is a genuinely unbounded feed of many uniform rows, where the
estimate converges and laziness pays for itself. Nothing in this app is one today.

```bash
grep -rn "LazyVStack(\|LazyHStack(\|LazyVGrid(" apps/macos/TAMForge/
```

No output, or the restyle reintroduced the bug.

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
   `A10000000000000000000094`, and, when the test bundle needs the resource at
   runtime too — as `openapi.yaml` and the Figtree fonts already do — unit-test
   Resources `E200000000000000000000A2`

Then, before building:

```bash
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj
```

A malformed project file produces a confusing `xcodebuild` error; the lint says
what is wrong.

## Measuring against the handoff

The eye does not see a uniform offset. Stage 2 shipped the whole shell 32 pt low —
brand mark at 89 against the handoff's 58, first nav row at 138 against 106 — and a
gate step that said "check the row pill geometry" passed it, because every element
was wrong by the same amount and the spacing between them looked right. Compare
numbers, not impressions.

**The expected numbers come from the handoff's markup.** `TAM Forge - Mac.dc.html`
states geometry as literal pixels in inline styles: the sidebar is `width:232px`,
the traffic-light strip `height:52px`, the brand row `padding:6px 18px 18px` around
a 30 pt tile, the nav container `padding:0 10px` with `gap:2px` around `height:36px`
rows. Add them down the axis before launching anything — the tile at 52 + 6 = 58,
the first nav row at 58 + 30 + 18 = 106, every next row 38 lower — so the check has
a number it can fail against.

**The measured numbers come from the accessibility tree.** Launch the Debug binary
directly with the flags that skip sign-in, then subtract the window's own position
to get window-local points, which compare one to one with the handoff:

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build
PRODUCTS="$(xcodebuild -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -showBuildSettings 2>/dev/null | awk -F' = ' '/ BUILT_PRODUCTS_DIR/{print $2}' | head -1)"
nohup "$PRODUCTS/TAMForge.app/Contents/MacOS/TAMForge" -ui-test-signed-in -ui-test-native-features >/dev/null 2>&1 &
osascript -e 'tell application "System Events" to tell process "TAMForge" to count windows'
```

```bash
osascript <<'MEASURE'
tell application "System Events" to tell process "TAMForge"
  set {wx, wy} to position of window 1
  set {ww, wh} to size of window 1
  set out to "window " & ww & "x" & wh & linefeed
  repeat with e in (UI elements of (item 1 of (groups of window 1)))
    set {ex, ey} to position of e
    set {ew, eh} to size of e
    set out to out & (role of e) & " " & (name of e) & " @ " & (ex - wx) & "," & (ey - wy) & " " & ew & "x" & eh & linefeed
  end repeat
  return out
end tell
MEASURE
```

Five things the run depends on:

- **Retry the launch.** The app comes up with zero windows on roughly two launches
  out of three, because it restores the window state it was closed with. `count
  windows` says which happened; relaunch up to three times before believing an empty
  tree.
- **Launch it detached.** A binary started as the foreground job of a tool call dies
  with the call. `nohup … &` outlives it.
- **`UI elements of (item 1 of (groups of window 1))` is the query that answers.**
  That group is the shell; the window's other children are the three traffic lights.
  `entire contents of window 1` is slow and intermittently returns nothing at all,
  which reads as an empty window rather than as a failed query.
- **One instance at a time.** `tell process "TAMForge"` cannot tell two builds apart,
  and every worktree builds its own. `pgrep -fl MacOS/TAMForge` before launching.
- **Decorative shapes are absent from the tree.** The brand tile, the toolbar bar and
  the nav pill backgrounds have no element; the labels inside them do. The 22 pt
  "TAM Forge" text centres in the 30 pt tile, so text at y 62 puts the tile at 58.
  Measure what the tree exposes and derive its expected number, rather than naming a
  container that is not there.

**A window floor is a read-back, not a request.** AppleScript's resize is clamped,
not refused, so a floor that is wrong looks exactly like one that holds:

```bash
osascript -e 'tell application "System Events" to tell process "TAMForge" to set size of window 1 to {900, 640}' \
          -e 'tell application "System Events" to tell process "TAMForge" to get size of window 1'
```

`900, 640`, or the floor is wrong: stage 2 answered `900, 672`, because SwiftUI adds
the hidden title bar's 32 pt safe area to whatever minimum the content declares. Then
re-run the measurement at that size to confirm nothing clips there.

Stop the app scoped to the build under test, so a parallel worktree's app survives:

```bash
pkill -f "$PRODUCTS/TAMForge.app/Contents/MacOS/TAMForge"
```

## Testing

**Never run `TAMForgeUITests` on this machine unless you are explicitly asked
to.** XCUITest on macOS drives the app with real HID events against the window
server, and it has no headless or offscreen mode: for the whole run it owns the
cursor and the keyboard of the desktop session someone is sitting at. One
journey pass is 180 to 210 seconds, and anything that loops the suite — a
bisect, a flake hunt, a retry — locks the machine out for as long as the loop
runs. The `TAMForge` scheme contains that target, so a bare `test` is the
command that takes the mouse.

Local default, unit target only, never touches the cursor:

```bash
xcodebuild -jobs 2 -skipPackagePluginValidation \
  -project apps/macos/TAMForge.xcodeproj -scheme TAMForge \
  -destination 'platform=macOS' -only-testing:TAMForgeTests test
```

The UI tests belong to the `native-ui` job in `.github/workflows/ci.yml`, which
runs `-only-testing:TAMForgeUITests` on a macOS runner with nobody at the
keyboard. Push and read the job. If they genuinely have to run on a Mac in front
of you, use a second macOS user through fast user switching, or a different
machine; both keep the events out of the session you are working in.

`-only-testing` against a class the project does not contain matches nothing,
runs nothing, and still exits `TEST SUCCEEDED`. Never read that as a pass unless
the output also shows a non-zero test count.
