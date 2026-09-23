# Stage 3 — Organic content layer (fix the inside of every screen)

## What went wrong
Stage 2 styled only the shell: `OrganicSidebar`, `OrganicToolbar`, `SignInView`. Every feature view is still stock SwiftUI:
- `GroupBox` → grey system boxes (80+ uses)
- `.font(.largeTitle / .headline / .caption)` → SF Pro, not Figtree
- `.buttonStyle(.borderedProminent)` and default buttons → grey system buttons
- `.foregroundStyle(.secondary)` → cold system grey
- `.orange / .red / .green` → system colors that aren't in the palette
- `TextEditor` / `.roundedBorder` → white system fields
- each view adds its own `.padding()` inside the shell's padding, so content ends up double-indented

That's why the colors look right from the outside while the inside still looks like the old app.

## Files in this folder
- `Core/Design/OrganicStyles.swift`: new file. Adds type roles (`.organic(.h1)`), the GroupBox → card style, `.organicPrimary / .organicSecondary / .organicLink` buttons, `.organicField()` / `.organicEditor()`, `OrganicPageHeader`, `OrganicNotice`, `OrganicEmptyState`, `OrganicMetric`, `OrganicSectionTitle`, and the root modifier `.organicContentTheme()`.
- `Features/Today/TodayView.swift`: full replacement. This is the reference pattern: Focus layout with a hero task, task rows and a support strip.
- `Features/Roadmaps/RoadmapAdministrationView.swift`: replaces everything from `struct RoadmapAdministrationView` to the end of the file. The semantic diff presentation types above it stay as they are.

## Step 1: global switch (fixes about 70 % on its own)
1. Add `OrganicStyles.swift` to `apps/macos/TAMForge/Core/Design/`.
2. In `TAMForgeApp.swift`, inside `NativeWorkspaceView.body`, apply the theme to the route column:
   ```swift
   VStack(alignment: .leading, spacing: Organic.Space.p24) {
       if let banner = session.banner { … }
       routeDetail
   }
   .organicContentTheme()          // ← add
   .frame(maxWidth: 1120, alignment: .leading)
   ```
3. In `OrganicComponents.swift`, add `.modifier(OrganicDisabledDimming())` as the last line of `makeBody` in each of the three button styles. Without it, disabled buttons look the same as enabled ones.

With just this step:
- every GroupBox becomes a surface card (nested ones get a quiet fill)
- untyped `Text` uses Figtree
- `.secondary` resolves to warm muted
- default buttons become pills
- checkboxes and pickers pick up the terracotta tint

## Step 2: per-file find → replace (all feature views)
| Find | Replace with |
|---|---|
| `.font(.largeTitle)` (page title) | `OrganicPageHeader(kicker:title:subtitle:)`. If you must keep the Text: `.organic(.h1)` |
| `.font(.title)`, `.font(.title2)` | `.organic(.h2)` |
| `.font(.title3)` | `.organic(.h3)` |
| `.font(.headline)` | `.organic(.title)` |
| `.font(.subheadline).bold()` / `.fontWeight(.semibold)` | `.organic(.strong)` |
| `.font(.subheadline)` | `.organic(.small)` |
| `.font(.caption)` + `.foregroundStyle(.secondary)` | `.organic(.caption)` |
| small section label ("Stable roadmap spine") | `.organic(.kicker)` |
| `.font(.system(.body/.caption, design: .monospaced))` | `.organic(.mono)` |
| `.monospacedDigit()` on numbers | `.font(Organic.Font.tabular(.semibold, size: N))` |
| `.buttonStyle(.borderedProminent)` | `.buttonStyle(.organicPrimary)`. Use at most **one** per card: the main action |
| `.buttonStyle(.link)` | `.buttonStyle(.organicLink)` |
| `.foregroundStyle(.orange)` | `Organic.Color.warning` |
| `.foregroundStyle(.red)` | `Organic.Color.danger` (wrap errors in `OrganicNotice(…, tint: .danger)`) |
| `.foregroundStyle(.green)` | `Organic.Color.success` |
| `.background(.quaternary, in: Capsule())` | `OrganicMetric` or `OrganicTag` |
| `.background(.quaternary, in: RoundedRectangle(cornerRadius: 8))` | `.background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))` |
| `TextEditor(…).frame(minHeight: N)` | `TextEditor(…).organicEditor(minHeight: N)` (inside a card: `onSurface: true`) |
| `.textFieldStyle(.roundedBorder)` | `.organicField()` (inside a card: `onSurface: true`) |
| `ContentUnavailableView` | `OrganicEmptyState` |
| `ProgressView("…")` | same, plus `.controlSize(.small)` |
| `.padding()` on the ScrollView content | **remove it**. The shell already pads 36/32/40 |
| `.frame(maxWidth: 900)` | 960–1040 (Today/Progress/Evidence) or 820 for detail panes |
| field label above an input | `OrganicFieldLabel(title:) { … }` |

**Do not change:**
- `Toggle` style: tests use `app.checkBoxes[…]`
- `DisclosureGroup` style: tests use `app.disclosureTriangles[…]`
- any `accessibilityIdentifier`
- button titles that tests match by text
- the order of long sections in Roadmaps/Activity: tests scroll a fixed number of steps

## Step 3: per-screen layout (from `TAM Forge - Mac.dc.html`, 1a)
**Activity** (`ActivityWorkspaceView`, `SpokenAttemptPanel`, `SqlExecutionPanel`, `CoachPanel`, `StudyNotePanel`, `ReviewPanel`, `PronunciationDiagnostic`)
- Layout: `HStack(alignment: .top, spacing: 28)` with the main column and a 300 pt right rail.
- Main column:
  - header: block `OrganicTag`, then `.organic(.h2)` objective
  - Working output: the draft editor is `.organicEditor(minHeight: 260, monospaced: true)`
  - Commit Attempt A: the immutability checkbox, then one `.organicPrimary` "Commit…"
  - Immutable Attempt A: `OrganicNotice(systemImage: "lock", tint: .success, …)`
  - Mandatory self-review: fields in a 2-column `LazyVGrid`
- Right rail: "Assigned source", "What good looks like", "Spoken attempt", Coach, Study note, AI review. Each is a GroupBox, so they become cards automatically.
- Remove the "Focused timer" GroupBox from the page. The timer lives in the bottom bar (see README → Shell).

**Cards**
- Layout: main column plus a 300 pt rail.
- The due card is a custom r36 card with `shadowed: true`, padding 36/40, min height 340. It contains:
  - kicker "skill · card N of M"
  - question `.organic(.h2)`
  - answer `.organic(.body)`
  - grade buttons 0–5 as `.organicSecondary`, with the number in `accent400`
- "New card" and "Import" go in the rail.

**Progress**
- Layout: 1.4 : 1 columns.
- "Skills against targets": a 10 pt track per skill:
  - fill is `accent2_400` if at or above M1, otherwise `accent400`
  - a 2×16 pt tick marks M1
- Minutes per week: capsule bars; the current week is `accent400`.
- Saturday assessments: `Organic.Color.sageOn` card.

**Interviews / English classes**
- Layout: a 300 pt list on the left (rows r20, selected row `accentOn`) and a detail pane on the right (max 820).
- Detail pane:
  - `OrganicPageHeader` with the primary "Record…" button as the trailing view
  - the 3 fields in a Grid
  - notes `.organicEditor`
  - "Interview timeline" card with the dimension table
  - "Practice your answers aloud" and "Interview reference" become the cards below it

**Evidence**
- `OrganicPageHeader` plus filter chips (selected: `accent400` fill, `neutral900` text).
- Summary cards (skill / portfolio), 3 per row.
- The ledger as rows: When · Activity · Evaluator · Score · Weight · Counts tag. Keep the DisclosureGroups ("Confidence basis", "Snapshot manifest", "Raw dimension scores") native.

**Recording**
- While recording: a centred column with a 260 pt ring (accent layers) and a 32 pt clock, then Pause (secondary) and "Stop & seal" (primary).
- Idle: "Preflight and consent" and "Current recording setup" as cards, preflight items as rows with sage/accent dots.
- "Capture health" and "Pending encrypted recordings" go below as cards.

## Prompt for Claude Code
> Read `design_handoff_tam_forge_mac/README.md` and `stage-3-content/MIGRATION.md`. Do Step 1, then drop in the Today and Roadmaps files. Build, run `TAMForgeUITests`, and fix anything that breaks without renaming identifiers. Then go screen by screen (Activity, Cards, Progress, Interviews, Classes, Evidence, Recording) applying the Step 2 table and the Step 3 layout. Use the Today/Roadmaps files as the reference pattern. After each screen, rebuild and rerun its UI test. Don't touch models, networking, or accessibility identifiers.
