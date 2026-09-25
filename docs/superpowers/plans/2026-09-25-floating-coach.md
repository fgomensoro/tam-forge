# Floating Coach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A floating Coach chat reachable from every screen of the Mac app, aware of the screen, the activity, the task-guide step and the unsaved draft, and allowed on every block.

**Architecture:** The server gains a general Coach thread (a `coach_threads` row with no activity), a small `general_coach` role, and an optional working context on activity coach messages; the sealing of blocks is removed. The Mac app replaces the rail `CoachPanel` with a shell-level overlay (bubble plus panel) driven by one `CoachThreadModel` that talks to the activity thread on an activity route and to the general thread elsewhere.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2, pytest (backend, `apps/backend`); SwiftUI, XCTest (macOS app, `apps/macos`).

**Spec:** `docs/superpowers/specs/2026-09-25-floating-coach-design.md`

## Global Constraints

- Alembic revision ids are 32 characters or fewer. Adding one moves the head constant in `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py::test_alembic_has_exactly_one_linear_head`.
- Any new or changed HTTP operation: regenerate `apps/macos/TAMForge/openapi.yaml` with `uv run python scripts/ci/check_openapi.py --write` and update `FROZEN_OPENAPI_SHA256` in `scripts/ci/tests/test_check_openapi.py`.
- No Pydantic field typed `None` alone, no `dict` with constrained keys (OpenAPI 3.0 / Swift generator). Use lists of small objects and empty-string defaults instead of nullable fields where possible.
- Claude runs only through `AgentSdkRuntime` (subscription token only). Never add an API key path.
- Context limits: activity `step` 200 chars; `fields` at most 20 items, `name` 64 chars, `value` 4000 chars, 12000 chars total. General `screen` 1-64 chars, `summary` 4000 chars.
- The response field `coaching_allowed` stays and is always `true` (installed apps still decode it).
- Backend commands, from the repo root: `uv sync --all-extras --all-packages --all-groups`; unit `uv run pytest -q apps/backend/tests/unit infra/tests scripts/dev/tests scripts/ci/tests`; integration needs your own Postgres container (see Task 1); `uv run mypy apps/backend/src packages/protocol/src`; `uv run ruff check .`; `uv run ruff format --check <touched files>`; `uv run python scripts/ci/check_openapi.py`.
- macOS: before writing or changing any SwiftUI view, read `~/.claude/skills/macos-organic-ui/SKILL.md` (design tokens, accessibility identifiers, manual Xcode project wiring). Build and unit tests: `xcodebuild -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -derivedDataPath <scratch>/dd -only-testing:TAMForgeTests test CODE_SIGNING_ALLOWED=NO`. Never run the UI test target locally (it takes over the desktop).
- Commit identity: export `GIT_AUTHOR_NAME/GIT_COMMITTER_NAME="Francisco Gomensoro"` and `GIT_AUTHOR_EMAIL/GIT_COMMITTER_EMAIL="102269369+fgomensoro@users.noreply.github.com"`. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Execution order

- Wave 1 (parallel): **Task 1 → Task 2 → Task 3** run in series in the main worktree (they share the backend venv and `contracts.py`/`openapi.yaml`); **Task 4** runs at the same time in its own worktree (Swift only).
- Wave 2: **Task 5** after Task 4 is merged into the feature branch.

---

### Task 1: General thread storage (backend) — dependent chain start, independent of Task 4

**Files:**
- Modify: `apps/backend/src/tamforge_backend/coaching/models.py`
- Create: `apps/backend/alembic/versions/20260925_0041_general_coach.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py` (head constant)
- Test: `apps/backend/tests/integration/coaching/test_general_coach_thread.py`

**Interfaces:**
- Produces: `CoachThread.activity_instance_id: Mapped[int | None]`; index `uq_coach_threads_owner_general` (unique `owner_id` where `activity_instance_id IS NULL`); revision `20260925_0041_general_coach` with `down_revision = "20260924_0040_import_restaging"` (check `alembic/versions` for the real current head first and use it).

- [ ] **Step 1: Integration test (fails first).** Bring up a database: `docker run -d --name tfpg-floating -p 127.0.0.1:54381:5432 -e POSTGRES_USER=tamforge -e POSTGRES_PASSWORD=tamforge pgvector/pgvector:pg16`, then `docker exec tfpg-floating psql -U tamforge -c "create database tamforge_test"`. Mirror the fixture style of `apps/backend/tests/integration/coaching/test_coach_threads.py`. The test creates an owner, inserts a `CoachThread(owner_id=..., activity_instance_id=None)`, asserts it persists, asserts a second general thread for the same owner raises `IntegrityError`, and asserts two general threads for two different owners are fine.
- [ ] **Step 2: Run it.** `TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54381/tamforge_test uv run pytest -q -m "integration and not postgres_integration" apps/backend/tests/integration/coaching/test_general_coach_thread.py`. Expected: FAIL (NOT NULL violation).
- [ ] **Step 3: Model.** In `CoachThread`: `activity_instance_id: Mapped[int | None] = mapped_column(BigInteger)` and add to `__table_args__`:

```python
        # The owner's general thread: the Coach outside any activity, one per owner.
        Index(
            "uq_coach_threads_owner_general",
            "owner_id",
            unique=True,
            postgresql_where=text("activity_instance_id IS NULL"),
        ),
```
Import `Index` and `text` from `sqlalchemy`.
- [ ] **Step 4: Migration.** Copy the header style of the current head migration.

```python
"""The owner's general Coach thread: a coach thread with no activity, one per owner."""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0041_general_coach"
down_revision = "20260924_0040_import_restaging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "coach_threads", "activity_instance_id", existing_type=sa.BigInteger(), nullable=True
    )
    op.create_index(
        "uq_coach_threads_owner_general",
        "coach_threads",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("activity_instance_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_coach_threads_owner_general", table_name="coach_threads")
    general = "SELECT id FROM coach_threads WHERE activity_instance_id IS NULL"
    op.execute(f"DELETE FROM coach_evidence WHERE thread_id IN ({general})")
    op.execute(f"DELETE FROM coach_messages WHERE thread_id IN ({general})")
    op.execute("DELETE FROM coach_threads WHERE activity_instance_id IS NULL")
    op.alter_column(
        "coach_threads", "activity_instance_id", existing_type=sa.BigInteger(), nullable=False
    )
```
Update the head constant in `test_curriculum_schema.py`.
- [ ] **Step 5: Run** the new integration test, the existing `tests/integration/coaching` tests, and the unit suite. Expected: PASS.
- [ ] **Step 6: Commit** `Let a coach thread exist without an activity`.

---

### Task 2: Every block coachable, activity working context (backend) — after Task 1

**Files:**
- Modify: `apps/backend/src/tamforge_backend/agents/roles/contracts.py` (context kinds)
- Modify: `apps/backend/src/tamforge_backend/agents/roles/coach.py`
- Modify: `apps/backend/src/tamforge_backend/coaching/schemas.py`, `service.py`, `routes.py`
- Modify: every other caller of `coaching_allowed` (`grep -rn coaching_allowed apps/backend/src`)
- Test: `apps/backend/tests/unit/agents/` coach tests, `apps/backend/tests/unit/coaching/test_routes.py`, contracts tests, `apps/backend/tests/integration/coaching/test_coach_threads.py`
- Regenerate: `apps/macos/TAMForge/openapi.yaml`, `scripts/ci/tests/test_check_openapi.py`

**Interfaces:**
- Produces: `contracts.WORKING_DRAFT = "working_draft"`, `contracts.SCREEN_CONTEXT = "screen_context"`, both in the COACH contract's `allowed_context`.
- Produces: `CoachRequest.working_step: str = ""`, `CoachRequest.working_fields: tuple[tuple[str, str], ...] = ()`.
- Produces: schemas `CoachDraftField(name: str 1-64, value: str ≤4000)`, `CoachWorkingContext(step: str ≤200 = "", fields: list[CoachDraftField] ≤20 = [])` with a total-length validator (12000), `CoachMessageCommand.context: CoachWorkingContext = CoachWorkingContext()`.
- Produces: `CoachThreadService.send(*, owner_id, activity_id, text, context: CoachWorkingContext)`.

- [ ] **Step 1: Failing tests.**
  - coach role: a request whose block has `allowed_ai_role` `planner`, `analyst`, `none`, and an interviewer block with phase `sealed_final_mock`, all produce a turn through `CoachService.turn` with a fake transport (no `RoleContractError`); an interviewer block before the commit is coached (no refusal).
  - `render_coach_prompt` with `working_step="Do it"` and `working_fields=(("audience", "CFO"),)` contains `Do it`, `audience: CFO`, and the words `unsaved` and `not evidence`.
  - `next_step_for` on an uncommitted interviewer activity returns `"Write your independent attempt; ask the coach for a hint only when stuck."`.
  - route: `POST /api/v1/activities/{id}/coach/messages` with `{"text": "hola"}` still works (context defaults); with 21 fields, a 65-char name, or 12001 total chars returns 422; the service receives the context.
  - response `coaching_allowed` is `true` for a planner block.
- [ ] **Step 2: Run** `uv run pytest -q apps/backend/tests/unit/agents apps/backend/tests/unit/coaching`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `contracts.py`: add the two kinds, export them, add both to the COACH contract.
  - `coach.py`: delete `coaching_allowed`, `COACHING_ROLES` and `SEALED_MOCK_PHASE` (and their `__all__` entries) and the two refusals in `CoachService.turn` and `draft_note` (keep the `draft_note` "only after the learner commits" check). Request gains the two fields. `turn` passes `WORKING_DRAFT` in `requested_context` when `working_fields` or `working_step` is set. In `render_coach_prompt`, after the phase lines:

```python
    if request.working_step or request.working_fields:
        lines.append(
            "Where the learner is standing (unsaved, not evidence; use it to aim the hint, "
            f"never grade it): step: {request.working_step or 'unknown'}"
            + "".join(f"\n- {name}: {value}" for name, value in request.working_fields)
        )
```
  - `service.py`: `next_step_for` drops the interviewer branch and the `allowed_ai_role` parameter's use (keep the parameter only if other callers pass it; otherwise remove it and fix callers). `send` takes `context` and fills `working_step=context.step.strip()`, `working_fields=tuple((f.name, f.value) for f in context.fields if f.value.strip())`. `_response` sets `coaching_allowed=True` with the comment `# Kept for apps installed before every block was coachable.`
  - `routes.py`: pass `command.context` to `service.send`.
- [ ] **Step 4: OpenAPI.** `uv run python scripts/ci/check_openapi.py --write`, update `FROZEN_OPENAPI_SHA256`, and compare construct counts in `openapi.yaml` against `origin/main` (no new `type: null`, no `propertyNames`).
- [ ] **Step 5: Run** unit suite, the coaching integration tests (Task 1 database), mypy, ruff, openapi check. Expected: PASS.
- [ ] **Step 6: Commit** `Coach every block and give it the learner's step and unsaved draft`.

---

### Task 3: General Coach thread and role (backend) — after Task 2

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/roles/general_coach.py`
- Modify: `apps/backend/src/tamforge_backend/agents/sdk_runtime.py` (system prompt + `general_reply`)
- Create: `apps/backend/src/tamforge_backend/coaching/general.py` (service)
- Modify: `apps/backend/src/tamforge_backend/coaching/schemas.py`, `routes.py`, `apps/backend/src/tamforge_backend/api.py` (register router)
- Test: `apps/backend/tests/unit/agents/test_general_coach.py`, `apps/backend/tests/unit/coaching/test_general_routes.py`, `apps/backend/tests/integration/coaching/test_general_coach_thread.py` (extend), `apps/backend/tests/unit/agents/test_sdk_runtime.py`
- Regenerate: OpenAPI files as in Task 2.

**Interfaces:**
- Consumes: `contracts.SCREEN_CONTEXT`, `CoachUnavailable` from `roles/coach.py`, `CoachThread` with nullable activity (Task 1), `CoachingUnavailable`/`CoachingInvalidRequest` from `coaching/service.py`, `CoachMessageResponse` from `coaching/schemas.py`.
- Produces:

```python
# agents/roles/general_coach.py
GENERAL_COACH_SCHEMA_ID = "urn:tamforge:schema:general-coach-v1"

class GeneralCoachTurn(BaseModel):  # extra="forbid"
    message: str  # 1..2000

@dataclass(frozen=True, slots=True)
class GeneralCoachRequest:
    screen: str
    summary: str
    learner_message: str
    prior_messages: tuple[tuple[Literal["learner", "coach"], str], ...] = ()
    repair_errors: tuple[str, ...] = ()

class GeneralCoachTransport(Protocol):
    async def general_reply(self, request: GeneralCoachRequest) -> Mapping[str, object]: ...

def general_coach_schema() -> dict[str, object]: ...
def validate_general_turn(payload: Mapping[str, object]) -> tuple[str, ...]: ...
def render_general_prompt(request: GeneralCoachRequest) -> str: ...

class GeneralCoachService:
    def __init__(self, transport: GeneralCoachTransport | None, *, model: str) -> None: ...
    async def reply(self, request: GeneralCoachRequest) -> GeneralCoachTurn: ...

# coaching/schemas.py
class GeneralCoachContext(StrictModel):   # screen 1..64, summary <=4000 = ""
class GeneralCoachMessageCommand(StrictModel):  # text 1..8192, context: GeneralCoachContext
class GeneralCoachThreadResponse(StrictModel):  # thread_id: int | None, messages: list[CoachMessageResponse]

# coaching/general.py
class GeneralCoachThreadService:
    def __init__(self, session: AsyncSession, *, coach: GeneralCoachService, clock=utc_now) -> None: ...
    async def thread(self, *, owner_id: int) -> GeneralCoachThreadResponse: ...
    async def send(self, *, owner_id: int, text: str, context: GeneralCoachContext) -> GeneralCoachThreadResponse: ...

# routes: GET /api/v1/coach, POST /api/v1/coach/messages (tags=["coaching"], same CSRF/owner deps and no-store headers as the activity routes)
```

- [ ] **Step 1: Failing tests.**
  - role: `validate_general_turn({"message": "ok"}) == ()`; missing message and `{"message": "I recorded your answer"}` return issues; `render_general_prompt` contains the screen, the summary, prior messages and the learner message; `GeneralCoachService(None, model="m").reply(...)` raises `CoachUnavailable`; with a fake transport it returns the turn.
  - runtime: `AgentSdkRuntime(...).general_reply(request)` sends `GENERAL_COACH_SYSTEM_PROMPT` and the general schema (reuse the `FakeQuery` helpers in `test_sdk_runtime.py`).
  - routes: GET returns `{"thread_id": null, "messages": []}` for a fresh owner; POST with `{"text": "hola", "context": {"screen": "Today", "summary": "- block A (ready)"}}` returns both messages; empty screen or a 4001-char summary is 422; Claude disabled answers 503 `coach_unavailable`.
  - integration: two POSTs create exactly one general thread; activity threads of the same owner are untouched.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** following `roles/coach.py` (`CoachService.turn`: `prepare_role_prompt(AgentRole.COACH, committed=False, requested_context=(SCREEN_CONTEXT,))`, `BoundedClaudeRuntime` with an adapter like `_RuntimeAdapter`, `PreparedAgentRun(run_key=f"general-coach:{digest}", job_type=COACH_JOB_TYPE, schema_id=GENERAL_COACH_SCHEMA_ID, prompt_version="v1", max_turns=COACH_MAX_TURNS, wall_time_seconds=COACH_WALL_TIME_SECONDS)`). `validate_general_turn` refuses the markers `"i recorded", "i scheduled", "i marked", "i completed", "i changed your plan"`. The prompt:

```python
def render_general_prompt(request: GeneralCoachRequest) -> str:
    lines = [f"Screen the learner is on: {request.screen}."]
    if request.summary:
        lines.append("What that screen shows:\n" + request.summary)
    for speaker, text in request.prior_messages:
        lines.append(f"{speaker}: {text}")
    lines.append(f"learner: {request.learner_message}")
    if request.repair_errors:
        lines.append("Your previous answer was refused; fix these:\n" + "\n".join(f"- {e}" for e in request.repair_errors))
    return "\n\n".join(lines)
```
System prompt in `sdk_runtime.py`:

```python
GENERAL_COACH_SYSTEM_PROMPT = (
    "You are the TAM Forge coach, outside any single study block. The learner can ask about "
    "their plan, what to study next, a concept, or how to use the app. Ground every answer in "
    "the screen context you are given and say so when it does not contain what they ask. "
    "Never claim to have recorded, scheduled, changed or completed anything. Answer in the "
    "learner's language, briefly. Return only the object."
)
```
`general_reply` mirrors `respond` (model `TAMFORGE_COACH_MODEL`, default `"claude-opus-5"`, `max_turns=4`). The service keeps the last 20 messages as `prior_messages` (same `PRIOR_MESSAGE_LIMIT` as the activity service), locks the general thread row on send (`with_for_update`), creates it on first send, stores the learner and coach messages, and maps `CoachUnavailable` to `CoachingUnavailable` and `RoleContractError` to `CoachingInvalidRequest`. Route dependency: transport is `app.state.coach_transport` when `settings.claude_enabled`, else `None`; model `settings.coach_model`. Register the new router in `api.py` next to the coaching router.
- [ ] **Step 4: OpenAPI** regenerate and check as in Task 2.
- [ ] **Step 5: Run** the full backend gate (unit, coaching integration, mypy, ruff, openapi). Expected: PASS. Remove the `tfpg-floating` container when the backend chain is done.
- [ ] **Step 6: Commit** `Add the general Coach thread for screens outside an activity`.

---

### Task 4: Coach model and API for a floating chat (Swift) — independent, own worktree

**Files:**
- Modify: `apps/macos/TAMForge/Features/Coaching/CoachModels.swift`
- Modify: `apps/macos/TAMForge/Features/Coaching/CoachService.swift`
- Modify: `apps/macos/TAMForge/Features/Coaching/CoachThreadModel.swift` (rewrite; keep the file and class name so no Xcode project wiring is needed)
- Test: `apps/macos/TAMForgeTests/CoachThreadModelTests.swift` (rewrite)

**Interfaces:**
- Produces:

```swift
struct CoachDraftField: Encodable, Equatable, Sendable { let name: String; let value: String }
struct CoachWorkingContext: Encodable, Equatable, Sendable { let step: String; let fields: [CoachDraftField] }
struct CoachScreenContext: Encodable, Equatable, Sendable { let screen: String; let summary: String }
struct GeneralCoachThread: Decodable, Equatable, Sendable { let threadID: Int?; let messages: [CoachMessage] }  // keys thread_id, messages

@MainActor protocol CoachAPI {
    func thread(activityID: Int) async throws -> CoachThread
    func send(activityID: Int, text: String, context: CoachWorkingContext) async throws -> CoachThread
    func acceptEvidence(activityID: Int, messageID: Int, index: Int) async throws -> CoachThread
    func generalThread() async throws -> GeneralCoachThread
    func sendGeneral(text: String, context: CoachScreenContext) async throws -> GeneralCoachThread
}

/// What the screens tell the floating coach about where the owner is standing.
struct ActivityStanding: Equatable, Sendable {
    let activityID: Int
    let block: String          // e.g. "Technical Learning"
    let stepLabel: String?     // TaskGuide step text, e.g. "Do it"
    let stepNumber: Int?       // 1-based
    let stepCount: Int
}

@MainActor final class CoachContext: ObservableObject {
    @Published var route: ShellRoute = .today
    @Published var activity: ActivityStanding?
    @Published var todaySummary: String = ""
    var draftFields: () -> [CoachDraftField] = { [] }   // set by the activity screen while shown
    static func todaySummary(_ snapshot: TodaySnapshot) -> String  // "- <objective> (<block>, <state>, <n> min)" per task, in roadmapOrder
}

@MainActor final class CoachThreadModel: ObservableObject {
    @Published var isPresented: Bool
    @Published var draft: String
    @Published private(set) var activityThread: CoachThread?
    @Published private(set) var generalThread: GeneralCoachThread?
    @Published private(set) var isBusy: Bool
    @Published private(set) var errorMessage: String?
    let context: CoachContext
    init(api: any CoachAPI, context: CoachContext)
    var activityID: Int? { get }            // non-nil on .activity(id)
    var title: String { get }               // "Activity 19 · Step 2 of 5 · Technical Learning" or the screen name
    var messages: [CoachMessage] { get }    // of the current target
    var canSend: Bool { get }
    func toggle() async                     // flips isPresented; loads the current target when opening
    func reload() async                     // loads the current target's thread
    func routeChanged() async               // when presented: drop a thread that no longer matches, reload
    func send() async
    func accept(messageID: Int, index: Int) async   // activity target only
    func dismissError()
}
```
Screen names for `title` off an activity: Today, Roadmaps, Recording, Interviews, English classes, Cards, Progress, Evidence.

- [ ] **Step 1: Failing tests** in `CoachThreadModelTests.swift` with a `FakeCoachAPI` that records calls and the last context:
  - on `.today`, `toggle()` presents and loads `generalThread()`; `send()` calls `sendGeneral` with `CoachScreenContext(screen: "Today", summary: context.todaySummary)` and clears the draft;
  - on `.activity(19)` with a standing (step 2 of 5, "Do it") and `draftFields` returning one non-empty field, `send()` calls `send(activityID: 19, ...)` with `CoachWorkingContext(step: "Do it", fields: [...])`;
  - `title` is `"Activity 19 · Step 2 of 5 · Technical Learning"` on the activity and `"Roadmaps"` on `.roadmaps`;
  - `routeChanged()` from `.activity(19)` to `.today` while presented loads the general thread; while not presented it loads nothing;
  - `todaySummary` renders one line per task ordered by `roadmapOrder`;
  - a thrown `.unavailable` sets `errorMessage` and keeps the draft.
- [ ] **Step 2: Run** the macOS unit tests (Global Constraints command). Expected: FAIL to compile or FAIL.
- [ ] **Step 3: Implement.** `LiveCoachAPI` sends `{"text", "context": {"step", "fields": [{"name", "value"}]}}` on the activity route (sorted keys) and uses `GET /api/v1/coach` and `POST /api/v1/coach/messages` with `{"text", "context": {"screen", "summary"}}` for the general thread, with the same error translation. Remove the old `CoachThreadModel(activityID:api:)` API; the `.notAllowed` special case goes away (every block is coachable). Keep `NativeActivityScreen` compiling by removing its `CoachThreadModel` construction and passing `coach: nil` to `ActivityWorkspaceView` for now (Task 5 removes the parameter).
- [ ] **Step 4: Run** the macOS unit tests. Expected: PASS.
- [ ] **Step 5: Commit** `Drive the coach from one model that follows the screen`.

---

### Task 5: Floating overlay and screen context wiring (Swift) — after Task 4

**Files:**
- Modify: `apps/macos/TAMForge/Features/Coaching/CoachPanel.swift` (becomes the floating panel plus the bubble container `CoachOverlay`)
- Modify: `apps/macos/TAMForge/Features/Activities/ActivityWorkspaceView.swift` (remove the rail coach and the `coach` parameter)
- Modify: `apps/macos/TAMForge/App/TAMForgeApp.swift` (own `CoachContext` and `CoachThreadModel`, overlay the detail column, publish route, Today summary and activity standing)
- Test: `apps/macos/TAMForgeTests/CoachThreadModelTests.swift` (standing publication helper if extracted), plus a build of the app target

**Interfaces:**
- Consumes: everything Task 4 produces; `TaskGuide.steps(for:)`, `TaskGuide.currentStep(for:)`; `ActivityWorkspaceModel.draft.values`; `TodayViewModel.snapshot`.
- Produces: accessibility identifiers `coachBubble`, `coachPanel`, `coachContextTitle`, `coachDraft`, `coachSend`, `coachError`, `coachNextStep`, `coachAssistanceMode`.

- [ ] **Step 1: Read** `~/.claude/skills/macos-organic-ui/SKILL.md`.
- [ ] **Step 2: Failing test** for a pure helper `ActivityStanding.from(activity: ActivityDetail) -> ActivityStanding` (block display name from `taskContract.block`, step label and 1-based number from `TaskGuide`, `stepCount` from `TaskGuide.steps(for:)`), placed in `CoachThreadModel.swift`, tested in `CoachThreadModelTests.swift` with an `ActivityDetail` fixture used by `TaskGuideTests.swift`.
- [ ] **Step 3: Implement the overlay.** `CoachOverlay(model:)`: a `VStack(alignment: .trailing)` with the panel (when `isPresented`) above a 52 pt circular accent button (`bubble.left.and.bubble.right.fill`, `coachBubble`, help text "Coach"). The panel: 380 × 520 pt, organic card surface and shadow, header with `model.title` (`coachContextTitle`) and a close button, a `ScrollViewReader` over the messages (activity thread: next step, assistance note, evidence proposals with Accept, reusing today's conversation rendering; general thread: messages only) that scrolls to the newest message, the draft `TextEditor` (`coachDraft`), Send (`coachSend`, ⌘↩) with a progress indicator while busy, and the error label (`coachError`).
- [ ] **Step 4: Wire the shell.** In the shell that renders `routeDetail`, own `@StateObject` `CoachContext` and `CoachThreadModel(api: services.coaching, context:)`; add `.overlay(alignment: .bottomTrailing) { CoachOverlay(model: coach).padding(Organic.Space.p24) }` to the detail `VStack` so it sits outside every route's scroll view; set `coachContext.route` initially and in `.onChange(of: session.selectedRoute)` then `await coach.routeChanged()`; update `coachContext.todaySummary` from `state.today.snapshot` whenever it changes. In `NativeActivityScreen`, publish `ActivityStanding.from(activity:)` into the shared `CoachContext` when the activity loads or its state changes and set `draftFields` to read `model.draft.values` (non-empty, sorted by key) only while `activity.state.isEditable`; clear both on disappear. Pass the `CoachContext` down the same way the screen receives its other shared models.
- [ ] **Step 5: Remove the rail coach.** Delete `if let coach { CoachPanel(model: coach) }` from `rail` and the `coach` parameter from `ActivityWorkspaceView` and all call sites (including previews and fixtures).
- [ ] **Step 6: Run** the macOS build and unit tests. Expected: PASS. Do not run the UI test target locally.
- [ ] **Step 7: Commit** `Float the coach over every screen`.

---

## Final gate (conductor)

Run everything CI runs: backend unit, backend integration (own container), mypy, ruff, ruff format on touched files, openapi check, macOS build and unit tests. Push; CI's `native-ui` and `e2e` cover the rest.
