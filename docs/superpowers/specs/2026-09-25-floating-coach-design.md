# Floating, context-aware Coach

## Goal

The Coach is a floating chat the owner can open from any screen of the Mac app. It knows
where the owner is standing: inside an activity it sees the block, the current step of the
task guide and what the owner has typed so far; on any other screen it knows which screen
it is and, on Today, the day's plan. It is available on every block.

Today the Coach is a card at the bottom of the activity page's right rail
(`ActivityWorkspaceView.rail`), scrolls away with the page, only exists inside an activity,
and is sealed on every block whose AI role is not coach, tutor or (outside the sealed final
mock) interviewer.

## Decisions taken with the owner (2026-09-25)

- Everywhere in the app, with screen context. Outside an activity the Coach uses one
  general thread that is stored like any other thread.
- A bubble at the bottom right of every screen opens a chat panel that floats over the
  content, stays put while the page scrolls, and survives switching screens.
- Every block allows coaching, the sealed final mock included. Help before the commit is
  still recorded as assistance on the thread (`assistance_mode`), as it is today.
- The assignment-clarity redesign of the activity header is a separate, later project.

## Server

### Data

`coach_threads.activity_instance_id` becomes nullable. A thread with no activity is the
owner's general thread; a partial unique index (`owner_id` where `activity_instance_id IS
NULL`) keeps it to one per owner. The existing unique constraint and composite foreign key
keep applying to activity threads. The migration only relaxes a constraint and adds an
index; its downgrade deletes general threads (with their messages) before restoring NOT
NULL.

### Activity threads

- `coaching_allowed` no longer seals anything: every block may be coached. The response
  keeps the `coaching_allowed` field, always true, so an app installed before this change
  keeps decoding the thread.
- `next_step_for` loses the interviewer special case ("Commit Attempt A first; the coach
  answers after the commit"); before the commit every block reads "Write your independent
  attempt; ask the coach for a hint only when stuck."
- `POST /api/v1/activities/{id}/coach/messages` accepts an optional `context`:
  `{"step": str | null, "fields": {name: text}}`. Limits: step 200 characters, at most 20
  fields, field names 64 characters, each value 4000 characters, 12000 characters in
  total. The context goes into that turn's prompt only; it is not stored and is not
  evidence. Before the commit the prompt labels it as the owner's unsaved draft.

### General thread

- `GET /api/v1/coach` returns the general thread (`thread_id` null until the first
  message). `POST /api/v1/coach/messages` takes `{"text", "context": {"screen": str,
  "summary": str}}` (screen 64 characters, summary 4000) and returns the thread.
- A new role, `general_coach`, answers with `{"message"}` only: no next step, no proposed
  evidence, no hint accounting. Its system prompt: the TAM Forge coach outside a study
  block; help with the plan, studying and using the app, grounded in the screen context it
  is given; never claim to have recorded, scheduled or changed anything; answer in the
  learner's language.
- It runs through the same `AgentSdkRuntime`, so the subscription-only credential guard
  and token slots apply unchanged. Bounded like the activity coach (4 turns, 120 s).
- Errors map exactly like the activity routes: 503 `coach_unavailable`, 422 invalid.

## Mac app

### Floating chat

- A `CoachOverlay` sits in the shell (`TAMForgeApp` detail column) as a bottom-trailing
  overlay: a round button, and when open a panel about 380 × 520 pt above it. It is
  outside the routes' scroll views, so it never scrolls, and its open/closed state lives in
  the shell, so it survives route changes.
- The panel header names the context: "Activity 19 · Step 2 of 5 · Technical Learning" or
  the screen name ("Today", "Roadmaps", …).
- The body reuses the existing conversation view (messages, next step, assistance note,
  evidence proposals with Accept) for activity threads; the general thread shows messages
  only.
- The rail `CoachPanel` is removed from `ActivityWorkspaceView`.
- Both coach clients use the Claude-length transport from #421.

### Context

- A shell-owned `CoachContext` holds the current route and, while an activity screen is
  on screen, that activity's id, block name, current step (`TaskGuide.currentStep`, with
  the step's label) and a provider for the draft's non-empty fields.
- On `.activity(id)` the overlay talks to that activity's thread and sends
  `{"step", "fields"}` with each message. On every other route it talks to the general
  thread and sends `{"screen", "summary"}`; the summary is the day's plan (each block's
  title, block type and state) on Today and empty elsewhere.

## Out of scope

- The assignment-clarity header (next project).
- Rich summaries for Roadmaps, Evidence, Recording, Interviews, Classes, Cards, Progress.
- Tracking which field has focus; the draft fields stand for "what I'm working on".
- More than one general thread, and moving messages between threads.

## Rollout

`main` deploys the server automatically after a green CI run (#422). The server change is
backward compatible with the installed app (old routes and fields unchanged), so the order
is: merge (server deploys), then build and install the DMG.

## Testing

- Backend unit: `coaching_allowed` true for every role and the sealed mock; `next_step_for`
  without the interviewer case; the activity prompt includes the step and draft fields
  before the commit; context limits are enforced (422); general coach role schema,
  validation and prompt.
- Backend integration: migration up and down; general thread created once per owner,
  messages stored, activity threads unaffected; the activity route accepts `context`.
- OpenAPI snapshot regenerated (`scripts/ci/check_openapi.py --write`).
- Mac unit: the context builder per route (activity with step and fields, Today with plan
  summary, other screens); the overlay model picks the activity thread or the general
  thread and sends the matching context; open state survives a route change.
