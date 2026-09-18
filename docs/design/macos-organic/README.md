# Handoff: TAM Forge — macOS redesign (Organic, dark)

## Overview
Redesign of the TAM Forge SwiftUI macOS shell (`apps/macos/TAMForge`, repo `fgomensoro/tam-forge`, branch `main`). Same routes, models and copy semantics as today; new visual system (warm dark ground, terracotta + sage accents, Figtree type, pill/over-rounded geometry), a persistent bottom focus-timer bar, and a stronger Today ("Focus" layout: one hero task, rest collapsed).

## About the design files
`TAM Forge - Mac.dc.html` is a **design reference built in HTML** — not code to ship. Recreate it in **SwiftUI** using the existing view models (`TodayViewModel`, `ActivityWorkspaceModel`, `CardsModel`, `ProgressModel`, `InterviewsModel`, `ClassesModel`, `EvidenceLedgerModel`, `RoadmapAdministrationModel`, `RecordingCoordinator`, `ShellSessionModel`) and keep every `accessibilityIdentifier` already in the code (UI tests depend on them). `TAM Forge - Current.dc.html` is a recreation of what ships today, for comparison.

## Fidelity
**High-fidelity.** Colors, type, spacing, radii and copy are final. Recreate pixel-close; where SwiftUI can't match exactly (e.g. `color-mix`), pre-compute the hex listed under Design tokens.

## Shell (all routes)
Window min 1280×820 (current min 900×640 stays as hard minimum).
- **Sidebar** 232 pt, bg `sidebarBg`, right hairline `divider`. Traffic lights at y 52. Brand row: 30×30 r9 terracotta tile containing a 12 pt sage disc with a dark offset shadow (`-4,4` neutral-900), then "TAM Forge" Figtree 600 18 pt.
  - Nav items: 36 pt tall pills (r 999), padding 0 12, gap 10, icon 17 pt Lucide stroke 2.75, label 14 pt. Selected: bg `accentOn` (accent @26 %), text `accent-300`. Hover: neutral-100 @6 %. Badge pill (11 pt, `accentOn` bg, `accent-300` text): Today "3 left", Cards "14". Order: Today, Roadmaps, Evidence, Recording, Interviews, English classes, Cards, Progress (existing `NativeFeature` order).
  - Footer (border-top `divider`): status row "● Updates live · Local development" 12 pt neutral-400 with 8 pt sage dot (this replaces the toolbar `environmentLabel` + `NotificationConnectionStatusView`); avatar 28 pt circle `accent-2-700` with initial in `accent-2-100`; name 13 pt; "Sign out" ghost 12 pt neutral-400 (`signOutButton`).
- **Toolbar** 52 pt, bottom hairline: breadcrumb 13 pt neutral-400 left (e.g. "Today · Thursday, Sep 17", "Today › Task 03 · Communication (spoken)"); right: "Notifications" secondary pill 32 pt (Figtree 600 13, border `divider`, bell icon 14, unread count in 18 pt `accent-400` circle, 11 pt 700 neutral-900 text) → opens existing `NotificationListView` popover.
- **Bottom timer bar** 64 pt, bg `sidebarBg`, top hairline, padding 0 24, gap 18. Left→right: 40 pt circle `accent-400` play/pause button (icon neutral-900) → `ActivityWorkspaceModel.start/pause/resume`; two-line label (13 pt 600 "03 · Deliver a 3-minute incident update", 12 pt neutral-400 "Paused · Attempt A open"); clock Figtree 600 20 pt tabular; "/ 35 min" 12 pt neutral-400; spacer; 260 pt day-progress block ("Day focused" / "**65** / 240 · hard stop 255", 6 pt track neutral-100 @10 %, fill `accent-2-400` at focused/target, 2×12 pt `accent-400` marker at hardStop/target*… positioned at 94 %); "Sync now" ghost `accent-300` 13 pt → heartbeat. Hidden when no activity is open or timer state is none; replaces `RecordingGlobalStatusView` position (recording status moves into the Recording route + a red dot on the sidebar item).
- Content area scrolls; page padding 32 36 40; content max-width 1040–1120.

## Screens

### Today (Focus)
- Header: kicker 11 pt uppercase tracking .1em `accent-400` "Thursday · Sep 17, 2026 · Month 1 · Week 2 · Day 4"; h1 Figtree 600 32 pt −.02em "Good afternoon, Fran."; sub 15 pt neutral-400 "65 of 240 focused minutes. Hard stop at 255 — nothing gets added past it." Right: 76 pt conic ring (`accent-400` progress over neutral-100 @10 %, 60 pt inner disc `bg`, 18 pt 600 "27%") + "3 of 6 blocks" 13 pt 600 / "Saturday assessment in 2 days" neutral-400.
- Hero card (primaryContinue task): bg `surface`, r 32, padding 28 30, shadow lg. Row: order number 26 pt 600 `accent-400`; tags (11 pt, r 12: block tag `accentOn`/`accent-300`; "Required", "No AI before commit" neutral-100 @8 %/neutral-300); title 22 pt 600 lh 1.25; meta 14 pt neutral-400 "Paused at 12:40 of 35 min · Attempt A not yet committed · Source: …". Actions: primary "Resume activity" (bg `accent-400`, text neutral-900, 15 pt, padding 12 22, play icon) → `todayContinueButton`; secondary "Open task contract" (border `divider`) → DisclosureGroup content in a sheet/popover; right: "Pass criteria" label + 6 pt progress bar.
- "Rest of the day" h3 18 pt 600 + "Stable roadmap spine · 175 min remaining" 13 pt neutral-400. Rows are 999-radius pills, padding 12 16, gap 16: order 15 pt 600 neutral-400 (w 26) · 9 pt status dot (done sage-400, current accent-400, ready neutral-500) · block 12 pt neutral-400 (w 150) · objective 14 pt (line-through + 55 % opacity when done) · minutes 12 pt (w 64, right) · state pill 11 pt (w 96, neutral-100 @8 %). Row hover neutral-100 @4 %.
- Support strip: 4-col grid gap 12, cards r 22 padding 16 18, bg neutral-100 @4 % (Feedback card: `accent-2` @18 %, kicker `accent-2-300`). Kicker 11 pt uppercase .08em neutral-400; value 16 pt 600; detail 12 pt neutral-400. Cards: Carryovers, Interview, Self-review due, Feedback.
- Sunday/off, offline, stale, hard-stop states: reuse existing copy; render as a `surface` card r 24 with the Lucide icon in `accent-300` (hard stop) or `accent-2-300` (rest day). Daily-close form: same fields as `DailyCloseForm`, inputs styled as below.

### Activity workspace
Two columns: content `1fr` + right rail 300 pt, gap 28. Header: block tag + "Task 03 · 35 min · AI role: none" 12 pt; h1 26 pt 600 lh 1.2. State stepper: pills 12 pt (ready → active → committed → self-review), reached steps `accentOn`/`accent-300`, dots sage-400 (past) / accent-400 (current) / neutral-600; 18 pt hairline connectors. Segmented "Working output | Self-review" (`.seg`, border `divider`, selected bg `accent-400` text neutral-900); hint text 12 pt neutral-400 to its right.
- **Working output**: 2-col fields (label 12 pt neutral-400; input 40 pt, r 999, bg `surface`, border `divider`, 14 pt); "Independent draft" editor: r 24, bg `surface`, border `divider`, padding 18 20, min 260 pt, monospace 13 pt lh 1.7 neutral-200; header right "Markdown · 184 words · in memory only" 11 pt neutral-500. Footer row: immutability checkbox (18 pt radio-dot style, `accent-400`, copy unchanged) · spacer · "Attach file…" secondary · "Commit Attempt A" primary. `SqlExecutionPanel`, artifact-upload states, incomplete classification: same components restyled as `surface` cards r 24.
- **Self-review**: banner r 24 bg `accent-2` @16 % with lock icon `accent-2-300`, "Attempt A committed at 15:42 · sha256 a91f…c2e0" 600 + explanation 13 pt neutral-300; 6 fields in 2-col grid (min 82 pt, r 20, `surface`); score row: 5 circles 38 pt (selected `accent-400`/neutral-900, else border `divider`), "Submit self-review" primary.
- **Right rail** cards r 26 padding 20 bg `surface`: "Assigned source" (9 pt sage dot, path 13 pt, anchor 12 pt neutral-400, "Hide source" secondary 13 pt); "What good looks like" (Required output / Pass criteria / Evidence / Constraints, 13 pt 600 titles, neutral-300 body); "Spoken attempt" card bg accent @14 %, kicker `accent-300`, "Record answer" button bg `accent-400` with 10 pt dark disc.

### Cards
Header h1 28 pt "Cards" + "14 due today · 5 done · retrieval counts toward block 05"; segmented Written/Spoken right. Grid `1fr` + 300. Card: r 36, bg `surface`, padding 36 40 32, min 340, shadow lg, second stacked card behind (offset 8, surface @60 %). Kicker 11 pt `accent-400` "structured troubleshooting · card 6 of 14"; question 22 pt 600 lh 1.2; hairline; answer 15 pt lh 1.6 neutral-200 (code `accent-300` mono 13); grade buttons 0 Blank … 5 Easy (border `divider`, Figtree 600 13, number in `accent-400`); "Show answer" primary when hidden. Below: "Last card: next in 4 days, on Sep 21." 12 pt neutral-500. Rail: "New card" (3 inputs bg `bg`, "Add card" secondary) and "Import from roadmap" (bg neutral-100 @4 %, version input 110 pt, outcome 12 pt `accent-2-300`).

### Progress
h1 "Progress" + "4 of 14 skills at or past the month-one target." Grid 1.4fr/1fr gap 24. Skills card (r 30, `surface`, padding 24 26): title 16 pt 600 + "level · baseline → M1 → final" 12 pt; per skill: name 13 pt 600, values tabular neutral-400, 10 pt track (neutral-100 @8 %) with fill `accent-2-400` if ≥ M1 else `accent-400`, 2×16 pt neutral-100 marker at M1. Weeks card: 6 bars, r 999 999 8 8, `accent-2-500` (current `accent-400`), labels 11 pt; footer "This week: 612 / 1200 focused · 3 of 5 days closed". Saturday assessments card bg `accent-2` @16 %, rows 13 pt, scores `accent-2-200`.

### Interviews / English classes (same pattern)
Left list 300 pt (right hairline, padding 28 18): h1 24 pt + 34 pt `accent-400` "+" circle; rows r 20 padding 12 14 (title 14 pt 600, meta 12 pt neutral-400), selected `accentOn`. Detail (padding 28 36 40, max 820): tag + h2 24 pt 600 + meta 14 pt; primary "Record this interview/class" with 10 pt dark disc (disabled when `recording_prohibited` — show 12 pt `accent-300` note); 3-col inputs (Company/Role/Stage or Teacher/Starts/Expected with −/+ stepper); notes editor r 20 min 96. Interviews: "Interview timeline" card r 28 with `.table` (headers 11 pt uppercase neutral-400; rows 13 pt tabular; "Change since first" in `accent-2-300`) + "Recurring gap" block. Classes: recording card with transcript turns grid 44/64/1fr, timestamps neutral-500, speaker 600 (You `accent-300`, Teacher/Interviewer `accent-2-300`).

### Evidence
h1 "Evidence" + one-line description; filter chips right (selected `accent-400`/neutral-900, others outline `divider`). 3 summary cards r 26 (value 24 pt 600; TAM English "—" neutral-500). `.table`: When · Activity (title 600 + type 11 pt) · Evaluator · Score · Weight · Counts tag (qualifies sage @28 %/`accent-2-200`; discounted `accentOn`/`accent-300`; excluded/pending neutral-100 @8 %/neutral-300). Row hover neutral-100 @4 %. Cursor pagination: "Load older" secondary at the end.

### Recording
Centered column max 640: tag; 260 pt ring (accent @10 %, inset 28 accent @16 %, inset 56 solid `accent`) with 32 pt 600 neutral-900 clock; h1 26 pt "Encrypted locally. Transcribing on-device."; body 14 pt neutral-400; Pause (secondary) + "Stop & seal" (bg `accent-400`, 10 pt dark square); preflight row 12 pt neutral-400 "● Mic OK · ● Screen audio OK · ● 1.2 GB free · ● Power connected" (use existing preflight/monitor states; failing item → `accent-300`).

### Roadmaps
h1 + description + "Import package…" primary. Version rows r 26 padding 18 24 (active row bg `accent-2` @14 %): key 18 pt 600 (w 120), state tag, summary 13 pt neutral-300, date 12 pt, action secondary. "Semantic diff" card: counts (+added `accent-2-300`, changed `accent-300`, removed neutral-400) and 3-col grid 140/1fr/1fr with before (line-through neutral-500) / after.

### Sign in (signedOut phase)
520×400: traffic lights; left-aligned column padding 0 48 40: 72 pt app icon; h1 28 pt "TAM Forge"; sub 14 pt neutral-400 "Sign in to continue your study workspace. Local development."; primary "Sign in with GitHub" (GitHub mark 16 pt) = `signInButton`; footnote 12 pt neutral-500 "PKCE · 15-minute token in memory · refresh token in your Keychain only." `GlobalBannerView` when present: r 24, bg `surface`, icon `accent-300`.

## Interactions
- Sidebar selects `ShellSessionModel.select(route)`; Today "Resume activity" → `.activity(id)`; "Record …" → `.recording` and starts the coordinator.
- Timer bar play/pause toggles activity timer; clock updates every second (`TimelineView`).
- Segmented in Activity switches draft/self-review; commit moves to self-review and shows the sealed banner.
- Hovers: nav neutral-100 @6 %; rows neutral-100 @4 %; primary button hover `accent-300`, pressed `accent-500`; secondary hover text @7 %. Focus ring 2 pt `accent` offset 2. Transitions 150 ms ease-out.
- Reduce-motion: no ring/conic animation.

## Design tokens (dark theme — derived from Organic)
- `bg` #2B2620 = mix(neutral-900 #2e2b25 62 %, accent-900 #402310)
- `surface` #453B31 = mix(neutral-800 #474238 62 %, accent-900)
- `sidebarBg` #362C22 = mix(neutral-900 45 %, accent-900)
- `text` neutral-100 #f9f4ed · body neutral-200 #eee7db · muted neutral-400 #c0b6a5 · faint neutral-500 #a19786
- `divider` neutral-100 @11 % · subtle fill neutral-100 @4 % / @8 % / @10 %
- accent #c67139 · accent-300 #ffc6a5 · accent-400 #f6a06b (primary buttons, text neutral-900 #2e2b25) · accent-500 #d67f48 · `accentOn` = accent @26 %
- accent-2 (sage) #7a8a5e · 200 #e1eecc · 300 #ccdbb2 · 400 #aebf92 · 500 #8fa073 · 700 #56633f
- Type: Figtree (400/600/700) everywhere; headings 600 with −.02em; numbers tabular. Scale: 32 / 28 / 26 / 24 / 22 / 18 / 16 / 15 / 14 / 13 / 12 / 11 (kickers uppercase .08–.1em). Monospace for drafts/hashes: SF Mono 13.
- Radii: 999 (pills, inputs, nav, task rows), 36/32/30/28/26/24/22/20 (cards by size), 14 window.
- Shadows: lg `0 12px 32px rgba(46,43,37,.22)`; window `0 24px 64px rgba(0,0,0,.55)`.
- Spacing: 4 / 8 / 12 / 14 / 16 / 18 / 20 / 24 / 28 / 32 / 36 / 40.
- Icons: Lucide, stroke 2.75, 17 pt sidebar / 14 pt inline.

## App icon
Squircle (macOS mask), gradient 160° #3a2c22 → #2e2b25, inner top highlight white @8 %. Terracotta #c67139 disc at 17 % inset with 66 % diameter; sage #7a8a5e disc 37.5 % diameter, positioned at 45 % / 45 %. Sizes shown 128 / 64 / 32; export 1024 for `.icns`.

## Files
- `TAM Forge - Mac.dc.html` — the redesign (interactive; sidebar navigates all 9 routes; section 1c = icon + sign in)
- `TAM Forge - Current.dc.html` — recreation of the shipped SwiftUI shell
- `github.md` — source association / screen map
