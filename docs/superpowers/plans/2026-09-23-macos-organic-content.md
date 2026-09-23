# macOS Organic Content Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the inside of every route (Today, Activity workspace, Roadmaps, Evidence, Recording, Interviews, English classes, Cards, Progress) on the Organic design system, so the content matches the shell that already shipped.

**Architecture:** One new design file, `Core/Design/OrganicStyles.swift`, adds type roles, a GroupBox card style, button-style shorthands, field/editor modifiers and a handful of layout primitives. A single `.organicContentTheme()` on the shell's route column makes every feature view inherit Figtree, warm text colors, card GroupBoxes and pill buttons. Each screen is then restyled in its own view file, with no model, networking or identifier changes. Today and Roadmaps drop in from the handoff; the other screens follow them as the reference pattern.

**Tech Stack:** SwiftUI (macOS 14+), Xcode project with explicit file references, XCUITest in CI (`native-ui` job).

**Spec:** `docs/superpowers/specs/2026-09-17-macos-organic-redesign-design.md` (stages 3, 5, 6, 7, 8 minus the app icon). Pixel authority: `docs/design/macos-organic/README.md` and `docs/design/macos-organic/TAM Forge - Mac.dc.html`. Stage-3 handoff content (not in the repo): `/private/tmp/claude-501/-Users-frank-Documents-mias-tam-forge--claude-worktrees-optimistic-hellman-6d4082/f790fdff-1264-4576-bbd6-b01002fcd59f/scratchpad/zip/design_handoff_tam_forge_mac/stage-3-content/` (`Core/Design/OrganicStyles.swift`, `Features/Today/TodayView.swift`, `Features/Roadmaps/RoadmapAdministrationView.swift`). The migration guide is committed as `docs/design/macos-organic/stage-3-migration.md` (called `MIGRATION.md` below).

## Global Constraints

- Follow `.claude/skills/macos-organic-ui/SKILL.md` in full. It overrides anything below that disagrees.
- No `accessibilityIdentifier` may be renamed, dropped, or change element type. It may move to another view.
- `apps/macos/TAMForgeUITests/` is never edited. `git diff --stat origin/main -- apps/macos/TAMForgeUITests/` must print nothing.
- Button titles that `TAMForgeUITests.swift` matches by text keep their exact text. Before changing any visible string on a screen, grep the UI test file for it.
- Toggles stay `.checkbox` style, DisclosureGroups stay system style (tests query `checkBoxes[...]` and `disclosureTriangles[...]`).
- The order of long sections in Roadmaps and Activity does not change: tests scroll a fixed number of steps.
- No `LazyVStack`, `LazyHStack` or `LazyVGrid` anywhere in `apps/macos/TAMForge/`. Use `VStack`, `HStack` or `Grid`.
- No color literals: every color comes from `Organic.Color.*`. `.foregroundStyle(.secondary)` is allowed only where `.organicContentTheme()` maps it (it resolves to `muted`); prefer the explicit token.
- Interactive rows are `Button` with `.buttonStyle(.plain)`, never `.onTapGesture`.
- Do not touch models, services, networking, fixtures, or the bottom timer bar (stage 4 is out of scope). The Activity page keeps its "Focused timer" GroupBox because the bottom bar does not exist yet.
- Never run `TAMForgeUITests` locally. The UI suite runs in CI.
- Build: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build`
- Unit tests: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests test` (check the output shows a non-zero executed test count).
- Commit messages: conventional, prose in English, `feat(macos): ...`, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Per-screen verification (every task from 2 on runs all of it)

```bash
# 1. identifiers unchanged, repo-wide
diff <(git grep -hoE 'accessibilityIdentifier\("[^"]*"\)' origin/main -- apps/macos/TAMForge | sed 's/^[^:]*://' | sort -u) \
     <(grep -rhoE 'accessibilityIdentifier\("[^"]*"\)' apps/macos/TAMForge | sort -u)
# expected: no output

# 2. interpolated identifiers in the touched file are the same count as before
F=apps/macos/TAMForge/Features/<Screen>/<Screen>View.swift
diff <(git show origin/main:$F | grep -c accessibilityIdentifier) <(grep -c accessibilityIdentifier $F)
# expected: no output

# 3. no lazy stacks, no UI-test edits
grep -rn "LazyVStack(\|LazyHStack(\|LazyVGrid(" apps/macos/TAMForge/   # expected: no output
git diff --stat origin/main -- apps/macos/TAMForgeUITests/             # expected: no output

# 4. no system colors or system fonts left in the touched files
grep -nE "\.font\(\.(largeTitle|title|title2|title3|headline|subheadline|caption|body)\)|foregroundStyle\(\.(orange|red|green|gray)\)|borderedProminent|roundedBorder|ContentUnavailableView" $F
# expected: no output (or a comment in the commit explaining each survivor)

# 5. build + unit tests (commands in Global Constraints)
```

## File map

| File | Task | Change |
|---|---|---|
| `Core/Design/OrganicStyles.swift` | 1 | new, from the handoff |
| `Core/Design/OrganicComponents.swift` | 1 | `OrganicDisabledDimming` on the three button styles |
| `App/TAMForgeApp.swift` | 1 | `.organicContentTheme()` on the route column |
| `TAMForge.xcodeproj/project.pbxproj` | 1 | wire `OrganicStyles.swift` (4 edits, 2 build files) |
| `Features/Today/TodayView.swift` | 2 | replace with handoff version |
| `Features/Roadmaps/RoadmapAdministrationView.swift` | 3 | replace from `struct RoadmapAdministrationView` down |
| `Features/Activities/ActivityWorkspaceView.swift`, `SpokenAttemptPanel.swift`, and the panel views it hosts | 4 | restyle |
| `Features/Cards/CardsView.swift` | 5 | restyle |
| `Features/Progress/ProgressView.swift` | 6 | restyle |
| `Features/Interviews/InterviewsView.swift` | 7 | restyle |
| `Features/Classes/ClassesView.swift` | 8 | restyle |
| `Features/Evidence/EvidenceLedgerView.swift` | 9 | restyle |
| `Features/Recording/RecordingView.swift` | 10 | restyle (leave `RecordingGlobalStatusView` API intact) |

Tasks 2 to 10 each touch only their own files and are **independent** of each other. All of them depend on Task 1.

---

### Task 1: Content theme foundation (serial, first)

**Files:**
- Create: `apps/macos/TAMForge/Core/Design/OrganicStyles.swift` (copy of handoff `stage-3-content/Core/Design/OrganicStyles.swift`)
- Modify: `apps/macos/TAMForge/Core/Design/OrganicComponents.swift` (the three `makeBody` at lines ~39, ~56, ~72)
- Modify: `apps/macos/TAMForge/App/TAMForgeApp.swift:460-465`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Produces: `View.organic(_ role: OrganicText, color:)`, `OrganicText` (`h1 h2 h3 title strong body small caption kicker mono`), `.buttonStyle(.organicPrimary / .organicSecondary / .organicLink)`, `View.organicField(onSurface:)`, `View.organicEditor(minHeight:onSurface:monospaced:)`, `OrganicPageHeader`, `OrganicNotice`, `OrganicEmptyState`, `OrganicMetric`, `OrganicSectionTitle`, `OrganicFieldLabel`, `Organic.Color.warning/danger/success/sageOn`, `View.organicContentTheme()`. Exact signatures are whatever the handoff file declares; later tasks read that file.

- [ ] **Step 1:** Copy the handoff file into `Core/Design/`. Wire it into the pbxproj per the skill's "Adding a file to the Xcode project" (file ref, two `PBXBuildFile`, group `Core/Design`, app Sources `A10000000000000000000091` and unit-test Sources `A10000000000000000000092`). Run `plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj`, expect `OK`.
- [ ] **Step 2:** Build. Fix only compile errors that come from the handoff file disagreeing with current `OrganicTokens`/`OrganicComponents` (for example a helper that already exists under the same name). Do not change the existing primitives' behavior.
- [ ] **Step 3:** Append `.modifier(OrganicDisabledDimming())` as the last modifier in each of the three button styles' `makeBody`.
- [ ] **Step 4:** In `NativeWorkspaceView.body`, add `.organicContentTheme()` to the `VStack` that holds the banner and `routeDetail`, before `.frame(maxWidth: 1120, ...)`.
- [ ] **Step 5:** Build and run unit tests. Expected: `** TEST SUCCEEDED **` with a non-zero count.
- [ ] **Step 6:** Commit `feat(macos): add the Organic content theme and apply it to every route`.

### Task 2: Today (Focus layout)

**Files:** Modify `apps/macos/TAMForge/Features/Today/TodayView.swift` (full replacement with the handoff file).

- [ ] **Step 1:** Before replacing, list the identifiers and UI-test-matched strings in the current file: `grep -o 'accessibilityIdentifier("[^"]*")' TodayView.swift | sort -u` and grep each visible button title in `apps/macos/TAMForgeUITests/TAMForgeUITests.swift`.
- [ ] **Step 2:** Replace the file with the handoff version. Build. Where the handoff file references a model property or type that does not exist, adapt the view to the real `TodayViewModel` / `TodayFeature.swift` API; never change the model.
- [ ] **Step 3:** Re-run the step 1 list against the new file. Every identifier and test-matched title from step 1 must still be present with the same element type (a `Button` stays a `Button`, a `DisclosureGroup` stays one).
- [ ] **Step 4:** Run the per-screen verification block with `F=apps/macos/TAMForge/Features/Today/TodayView.swift`.
- [ ] **Step 5:** Commit `feat(macos): rebuild Today on the Organic focus layout`.

### Task 3: Roadmaps

**Files:** Modify `apps/macos/TAMForge/Features/Roadmaps/RoadmapAdministrationView.swift` (replace from `struct RoadmapAdministrationView` to end of file with the handoff version; the semantic-diff presentation types above it stay).

- [ ] Steps 1 to 4 as in Task 2, with `F` pointing to this file. Additional check: the order of the sections (package import, validation, semantic diff sections, approval gate) is the same as on `origin/main`, because `testNativeFoundationParityJourney` scrolls a fixed number of steps.
- [ ] Commit `feat(macos): restyle Roadmaps on Organic`.

### Tasks 4 to 10: restyle a screen (same recipe, one task per screen)

| Task | Screen | Files | Layout (from `MIGRATION.md` step 3 and README "Screens") |
|---|---|---|---|
| 4 | Activity workspace | `Features/Activities/ActivityWorkspaceView.swift`, `SpokenAttemptPanel.swift`, and the panel views defined for this page (`SqlExecutionPanel`, `CoachPanel`, `StudyNotePanel`, `ReviewPanel`, `PronunciationDiagnostic`, wherever they live) | `HStack(alignment: .top, spacing: 28)`: main column + 300 pt rail. Header: block `OrganicTag` + `.organic(.h2)` objective. Draft editor `.organicEditor(minHeight: 260, monospaced: true)`. Commit row: immutability checkbox, then one `.organicPrimary` "Commit…". Immutable attempt: `OrganicNotice(systemImage: "lock", tint: .success, …)`. Self-review fields in a 2-column `Grid`. Rail: Assigned source, What good looks like, Spoken attempt, Coach, Study note, AI review as GroupBoxes. **Keep** the "Focused timer" GroupBox (bottom bar is out of scope); move it to the top of the rail. |
| 5 | Cards | `Features/Cards/CardsView.swift` | Main column + 300 pt rail. Due card: custom card `organicCard(radius: r36, shadowed: true)`, padding 36/40, min height 340; kicker "skill · card N of M", question `.organic(.h2)`, answer `.organic(.body)`, grade buttons 0–5 `.organicSecondary` with the number in `accent400`. "New card" and "Import" in the rail. |
| 6 | Progress | `Features/Progress/ProgressView.swift` | 1.4 : 1 columns. Skills: 10 pt track per skill, fill `accent2_400` at or above M1 else `accent400`, 2×16 pt tick at M1. Minutes per week: capsule bars, current week `accent400`, others `accent2_500`. Saturday assessments on a `sageOn` card. |
| 7 | Interviews | `Features/Interviews/InterviewsView.swift` | 300 pt list left (rows r20, selected `accentOn`), detail right max 820: `OrganicPageHeader` with primary "Record…" trailing, 3 fields in a `Grid`, notes `.organicEditor`, "Interview timeline" card with the dimension table, then "Practice your answers aloud" and "Interview reference" cards. |
| 8 | English classes | `Features/Classes/ClassesView.swift` | Same pattern as Interviews. Transcript turns grid 44/64/1fr, timestamps `faint`, speaker semibold (You `accent300`, Teacher `accent2_300`). |
| 9 | Evidence | `Features/Evidence/EvidenceLedgerView.swift` | `OrganicPageHeader` + filter chips (selected `accent400` fill, `neutral900` text). Summary cards 3 per row, r26. Ledger rows: When · Activity · Evaluator · Score · Weight · Counts tag. Keep the DisclosureGroups native. "Load older" secondary at the end. |
| 10 | Recording | `Features/Recording/RecordingView.swift` | Recording: centered column, 260 pt ring (accent layers), 32 pt tabular clock, Pause (secondary) + "Stop & seal" (primary). Idle: "Preflight and consent" and "Current recording setup" as cards, preflight items as rows with sage/accent dots. "Capture health" and "Pending encrypted recordings" below as cards. `RecordingGlobalStatusView` keeps its initializer and identifiers (the shell uses it). |

Recipe for each of these tasks:

- [ ] **Step 1:** List identifiers and UI-test-matched strings for the files, as in Task 2 step 1. Read the screen's section of `docs/design/macos-organic/TAM Forge - Mac.dc.html` for the geometry numbers, and `Features/Today/TodayView.swift` + `Features/Roadmaps/RoadmapAdministrationView.swift` (after Tasks 2 and 3, or the handoff copies) as the code pattern.
- [ ] **Step 2:** Apply the `MIGRATION.md` step 2 find-and-replace table to every line of the files.
- [ ] **Step 3:** Apply the layout from the table above. Remove the page-level `.padding()` on the ScrollView content (the shell pads). Page title becomes `OrganicPageHeader`.
- [ ] **Step 4:** Build, then the per-screen verification block with `F` set to each touched file.
- [ ] **Step 5:** Commit `feat(macos): restyle <Screen> on Organic`.

No new unit tests: these are view-only changes with no new logic. If a task extracts a pure helper (for example a "reached M1" comparison), it gets a unit test in `apps/macos/TAMForgeTests/` first, red then green, wired into the pbxproj.

### Task 11: Integration and geometry gate (serial, last)

- [ ] **Step 1:** With all screen commits on `fg/macos-organic-content`, build and run unit tests.
- [ ] **Step 2:** Run the per-screen verification checks 1 and 3 repo-wide.
- [ ] **Step 3:** Geometry gate, per the skill's "Measuring against the handoff". Expected window-local numbers, derived from the shell (sidebar 232, toolbar 52, page padding 32 top / 36 left): the first element of each route's content starts at x = 232 + 36 = 268 and y = 52 + 32 = 84 (± 2). Measure Today (kicker text), Cards (page title) and Evidence (page title). Then read back the window floor `900, 640`.
- [ ] **Step 4:** Push, open the PR, read the `native-ui` job. It is the only place the UI suite runs.
