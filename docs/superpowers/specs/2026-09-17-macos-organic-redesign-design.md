# Rebuilding the macOS app on the Organic design system

Date: 2026-09-17. Status: agreed with Frank in brainstorming.

The design handoff lives in `docs/design/macos-organic/`. Its `README.md` is the
authority on pixels: colors, type, spacing, radii and copy are final there and
this document does not repeat them. `TAM Forge - Mac.dc.html` is the interactive
reference for all nine routes; `TAM Forge - Current.dc.html` recreates what ships
today, for comparison. Neither HTML file is code to port. This document covers
only what the handoff does not: how the system lands in SwiftUI, what it changes
in app behavior, and the order the work ships in.

## Where the app starts from

The shipping app is stock SwiftUI: `NavigationSplitView`, `List`, `Label`, system
buttons, no custom chrome and no design layer of any kind. There is no theme
file, no token file and no asset catalog. About 5,600 lines of view code across
nine routes get rewritten.

Two things constrain every decision below:

- 184 `accessibilityIdentifier` values and 987 lines of UI tests that run in CI on
  `macos-26`. Identifiers are a contract; the redesign moves views, not names.
- `TAMForge.xcodeproj/project.pbxproj` uses explicit file references, not
  Xcode 16 synchronized groups. Every new file is a hand edit to the project file,
  which is a standing argument for few files.

The data layer needs no changes. `TodayTimePolicy` already carries
`focusedMinutes`, `targetMinutes` and `hardStopMinutes`; `TodaySnapshot.primaryContinue`
is exactly the hero task the Focus layout wants; `ActivitySummary` already carries
`activityFocusedSeconds`, `dayFocusedMinutes` and `hardStopRecommended`, which is
everything the bottom bar's day-progress block needs. No backend work, no new
endpoints, no contract regeneration.

## Decisions taken with Frank on 2026-09-17

**Type is bundled, icons stay native.** Figtree ships with the app as three static
weights (400/600/700) plus an `ATSApplicationFontsPath` key in `Info.plist`.
Figtree is OFL-licensed, so the static weights are vendored from Google Fonts with
the license file alongside them. The typeface carries most of the Organic identity
and costs one resource directory and one plist key.

Icons stay SF Symbols rather than becoming a Lucide asset catalog: at 17 pt the
two read nearly the same, the app already maps every sidebar route to a sensible
symbol, and SF Symbols give optical alignment and Dynamic Type for free. This
keeps eight of the nine stages free of an asset catalog, which the project does
not have today. The app icon is the exception, since no SF Symbol substitutes for
it: stage 8 does add the project's first `.xcassets` for the `AppIcon` set alone,
which is why it is scheduled last and kept apart from everything else.

**The work ships in stages, not one branch.** Foundation first, then the shell,
then one or two screens per pull request. The app stays usable at every merge and
CI reports on a reviewable diff instead of a rewrite.

**The global recording stop survives.** The handoff moves recording status into
the Recording route and leaves a red dot on the sidebar item, which would mean
navigating to Recording to stop a running capture. That is a regression and we are
not taking it. See "The bottom bar" below.

## The design layer

Three new files under `TAMForge/Core/Design/`:

- `OrganicTokens.swift` — colors, fonts, radii, shadows and the spacing scale as
  static constants. Every value the handoff expresses as `color-mix` is stored
  pre-computed as the hex the handoff already lists, so nothing is blended at
  runtime.
- `OrganicComponents.swift` — the modifiers and small views that repeat across
  screens: `.organicCard(radius:)`, `.organicPrimary()`, `.organicSecondary()`,
  `OrganicTag`, `OrganicPill`, `OrganicTable`, the input and segmented-control
  styles, and the focus ring.
- `OrganicWindow.swift` — the window chrome: hidden title bar, a 1280×820 default
  size, and the top inset that clears the traffic lights at y 52. The existing
  900×640 stays as the hard minimum, per the handoff, so the layouts have to
  survive being squeezed below their design width.

A component earns its own type when it appears in three places. Until then it is
a modifier or it is inline. There is one theme, so there is no theme protocol and
no `@Environment` injection.

**The app becomes dark-only.** The handoff ships a single dark palette and no
light counterpart, so the window pins `.preferredColorScheme(.dark)`. Following
the system appearance would leave half the tokens undefined. If a light theme is
ever wanted, it is a new design pass, not a code change.

## The shell

`NativeWorkspaceView`'s `NavigationSplitView` is replaced by a plain `HStack`: a
232 pt sidebar built from the existing `NativeFeature` set, and the content
column. This is a deliberate trade. The custom sidebar gives the pill geometry,
the badges and the footer the design calls for, and gives up the native sidebar's
collapse behavior and material. The routes, the `ShellSessionModel.select` calls
and the feature gating are untouched.

The sidebar footer absorbs two things that live in the toolbar today: the
`environmentLabel` text and `NotificationConnectionStatusView`. `environmentLabel`
has zero references in the UI tests, so it moves for free. `signOutButton` appears
four times in the tests and keeps both its identifier and its recording guard.

## The bottom bar

This is the only part of the redesign that is not a rewrite of existing views, and
it is the riskiest.

The handoff puts a persistent 64 pt bar at the bottom of every route showing the
open activity's timer, its label, the day-progress block and a sync action. Today
`ActivityWorkspaceModel` is a `@StateObject` created inside `NativeActivityScreen`,
so it is destroyed the moment you navigate to Today and the bar would have nothing
to read.

The model already solves this and nobody uses it. `ActivityWorkspaceModel` has
`appear()` and `disappear()` and an `isVisible` flag that gates `available`, which
in turn gates the heartbeat loop. It is built to outlive its own visibility. So the
change is to hoist the `@StateObject` into `NativeWorkspaceState`, cached by
`activityID`, which is the pattern that object already uses for `today`, `cards`,
`evidence`, `drafts` and `timerJournal`. The current `.id(identifier)` semantics are
preserved as "new id, new model, old one released". `appear()` is called while an
activity is open on any route and `disappear()` only when it closes, so heartbeats
keep the server's focused time honest while you are reading Today.

This has a side benefit: an in-progress draft is no longer lost when you leave the
activity route to check something.

**Recording keeps its global stop.** The bar is the global status surface, and it
takes over the screen position `RecordingGlobalStatusView` occupies today, so the
recording controls move into the bar rather than out of the chrome. Concretely:

- The bar is visible when an activity is open **or** a recording is active. The
  handoff's rule ("hidden when no activity is open") is widened accordingly;
  with only a recording running, the bar shows only the recording segment.
- When a recording is active, a segment appears between the spacer and the
  day-progress block: the status dot, the elapsed time, and the stop control.
- `recordingGlobalStatus` and `recordingGlobalStopButton` keep their identifiers.
  Neither is currently referenced by the UI tests; the staged work adds coverage
  for stopping a recording from a non-Recording route, since that behavior was
  previously untested and is now something we have explicitly chosen to keep.
- The sidebar's red dot on the Recording item is additive, not a replacement.

## Behavior the redesign changes

Everything else is visual. These are the intentional functional changes, all
agreed above: the app is dark-only; the native split-view sidebar becomes a custom
one; the environment label and connection status move into the sidebar footer; the
activity model outlives its route; and the bottom bar hosts both the activity
timer and the recording controls.

## The identifier contract

Every stage ends with the full UI test suite green with no edits to
`TAMForgeUITests.swift`, except where a stage explicitly adds a test. An
identifier may move to a different view; it may not be renamed or dropped. A stage
that cannot hold this line stops and reports rather than editing the test to match.

## Staging

| Stage | Scope | Visible change |
|---|---|---|
| 1 | Figtree resources, `OrganicTokens`, `OrganicComponents`, `OrganicWindow` | none; foundation only |
| 2 | Shell: window chrome, sidebar, toolbar, sign-in screen, sidebar footer | large |
| 3 | Today (Focus layout) | large |
| 4 | Hoist `ActivityWorkspaceModel`; bottom bar with activity timer and recording controls | large |
| 5 | Activity workspace (working output, self-review, right rail) | large |
| 6 | Cards, Progress | moderate |
| 7 | Interviews, English classes | moderate |
| 8 | Evidence, Recording, Roadmaps, app icon | moderate |

Stage 1 lands without altering a single pixel, which makes it a cheap way to prove
the font bundling and the pbxproj edits before anything depends on them. Stage 4
depends on stage 3 only because the bar reads the same day-progress numbers Today
renders, and shipping them together keeps the two consistent.

## Risks

- **The pbxproj is edited by hand eight times.** A malformed edit breaks the CI
  build rather than failing quietly. Each stage verifies with a local
  `xcodebuild` before the pull request opens.
- **Hoisting the activity model is the one change that can corrupt study data.**
  A model that outlives its route while still heartbeating could double-report
  focused time if `appear()`/`disappear()` are wired wrong. Stage 4 is
  test-driven against the heartbeat coordinator before the bar is drawn at all.
- **Figtree has no tabular-figures guarantee across weights.** The design leans on
  tabular numbers for clocks and scores. If the bundled weights do not deliver
  them, the clock falls back to the system monospaced digit font, which is the
  smaller loss.
- **Pixel-close is a claim that needs checking.** Each screen stage compares the
  built app against its section of `TAM Forge - Mac.dc.html` before it is called
  done, rather than against the written description alone.
