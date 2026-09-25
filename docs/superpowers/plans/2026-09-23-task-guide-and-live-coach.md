# Task Guide and Live Coach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The activity screen lists the block's steps with the current one marked, and the Coach answers before Attempt A is committed, recording any help it gave as the attempt's assistance mode.

**Architecture:** The step guide is a pure Swift function of block type and activity state, rendered in a new panel above the working output. The Coach's "commit first" rule moves from refusal to recording: the coaching thread carries an `assistance_mode` that the coach service raises when it helps before the commit, and the learning service copies the stronger of the activity's and the thread's mode onto the attempt at commit time. The reviewer and the evidence formulas already treat `hint_ladder` as assisted work, so nothing downstream changes.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (apps/backend), SwiftUI macOS app with XCTest (apps/macos), pytest with `anyio`, uv.

**Spec:** `docs/superpowers/specs/2026-09-23-task-guide-and-live-coach-design.md`

## Global Constraints

- Backend commands run from the repo root with `uv run ...`; sync first with `uv sync --all-packages --all-extras --frozen`.
- Backend lint and types: `uv run ruff check .` and `uv run mypy apps/backend/src packages/protocol/src` must stay clean.
- Alembic revision ids are at most 32 characters.
- Every Pydantic response field that reaches the OpenAPI contract must be non-optional or the Swift generator breaks; after any schema change run `uv run python scripts/ci/check_openapi.py --write` and commit `apps/macos/TAMForge/openapi.yaml`.
- macOS: never write literal colors or system fonts; use `Organic.Color.*`, `Organic.Font.*`, `Organic.Space.*`, `Organic.Radius.*`. Never `LazyVStack`. Interactive rows are `Button` with `.buttonStyle(.plain)`.
- macOS: never rename or drop an existing `accessibilityIdentifier`. Never edit `apps/macos/TAMForgeUITests/`. Never run the UI test target locally.
- macOS unit tests: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests test`. Confirm the output shows a non-zero test count.
- Every new Swift file needs the four `project.pbxproj` edits (file reference, build files, group, build phase), then `plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj`.
- Deliverable text (code, comments, commit messages, UI copy) is English.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Task dependency map

- Independent, run in parallel: Task 1, Task 2, Task 5.
- Task 3 needs Task 2.
- Task 4 needs Task 3.
- Task 6 needs Task 3 and Task 5.

---

### Task 1: The Coach may speak before the commit (role contract)

**Files:**
- Modify: `apps/backend/src/tamforge_backend/agents/roles/contracts.py:36-38`
- Test: `apps/backend/tests/unit/agents/roles/test_coach.py`

**Interfaces:**
- Produces: `prepare_role_prompt(AgentRole.COACH, committed=False, requested_context=(TASK_BRIEF,))` returns a contract instead of raising.

- [ ] **Step 1: Change the tests**

In `apps/backend/tests/unit/agents/roles/test_coach.py` replace `test_the_coach_waits_for_the_attempt_and_the_self_review` and `test_no_role_but_the_planner_speaks_before_commitment` with:

```python
def test_the_coach_may_prepare_before_the_attempt_but_sees_only_its_context() -> None:
    contract = prepare_role_prompt(AgentRole.COACH, committed=False, requested_context=(TASK_BRIEF,))
    assert contract.role is AgentRole.COACH

    allowed = contract_for(AgentRole.COACH).allowed_context
    assert {TASK_BRIEF, COMMITTED_ATTEMPT, SELF_REVIEW} == set(allowed)
    assert SOURCE_MATERIAL not in allowed


@pytest.mark.parametrize("role", [AgentRole.TUTOR, AgentRole.REVIEWER, AgentRole.ANALYST])
def test_only_the_planner_and_the_coach_speak_before_commitment(role: AgentRole) -> None:
    assert ROLES_BEFORE_COMMITMENT == frozenset({AgentRole.PLANNER, AgentRole.COACH})
    with pytest.raises(RoleContractError, match="commits"):
        prepare_role_prompt(role, committed=False, requested_context=())
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_coach.py -q`
Expected: 2 failures, `RoleContractError` on the coach call and the frozenset assertion.

- [ ] **Step 3: Change the contract**

In `apps/backend/src/tamforge_backend/agents/roles/contracts.py` replace lines 36-38 with:

```python
# The Planner plans a day before anything is committed. The Coach may speak before the
# commit too: it asks the recall question and hands out hints, and every hint it gives
# before the commit is recorded on the attempt as assistance. Every other role needs a
# committed attempt in front of it.
ROLES_BEFORE_COMMITMENT: frozenset[AgentRole] = frozenset({AgentRole.PLANNER, AgentRole.COACH})
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_coach.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents/roles/contracts.py apps/backend/tests/unit/agents/roles/test_coach.py
git commit -m "Let the coach role prepare a prompt before the learner commits"
```

---

### Task 2: The Coach role knows its phase and reports hints

**Files:**
- Modify: `apps/backend/src/tamforge_backend/agents/roles/coach.py`
- Modify: `apps/backend/src/tamforge_backend/agents/sdk_runtime.py:132-141`
- Test: `apps/backend/tests/unit/agents/test_coach_service.py`

**Interfaces:**
- Produces: `COACHING_ROLES == {"coach", "tutor", "interviewer"}`; `CoachRequest.phase` property returning `"before_commit"` or `"after_commit"`; `CoachTurn.hint_given: bool`; `validate_coach_turn(payload, *, next_step, phase="after_commit")`; `CoachService.turn` accepts an empty `committed_attempt`.

- [ ] **Step 1: Write the failing tests**

In `apps/backend/tests/unit/agents/test_coach_service.py`, change `test_coaching_is_allowed_only_where_the_block_says_so` to:

```python
def test_coaching_is_allowed_only_where_the_block_says_so() -> None:
    assert coaching_allowed(BLOCK)
    assert coaching_allowed(CoachBlock("x", "o", "tutor", (), ()))
    assert coaching_allowed(CoachBlock("x", "o", "interviewer", (), ()))
    for sealed in ("none", "planner", "reviewer", "analyst"):
        assert not coaching_allowed(CoachBlock("x", "o", sealed, (), ()))
```

Add these tests after it:

```python
def test_the_phase_follows_the_committed_attempt() -> None:
    assert _request().phase == "after_commit"
    assert _request(committed_attempt="").phase == "before_commit"
    assert _request(committed_attempt="   ").phase == "before_commit"


def test_a_hint_is_only_recorded_before_the_commit() -> None:
    hinted = {**GOOD, "hint_given": True}
    assert validate_coach_turn(hinted, next_step=NEXT, phase="before_commit") == ()
    assert validate_coach_turn(hinted, next_step=NEXT, phase="after_commit") == (
        "a hint is recorded only before the commit",
    )
    assert validate_coach_turn(GOOD, next_step=NEXT, phase="before_commit") == ()


@pytest.mark.anyio
async def test_a_turn_before_the_commit_runs_and_tells_the_prompt_the_phase() -> None:
    transport = FakeTransport([{**GOOD, "hint_given": True}])
    service = CoachService(transport, model="claude-opus-5")

    turn = await service.turn(_request(committed_attempt="", learner_message="dame una pista"))

    assert turn.hint_given
    prompt = render_coach_prompt(transport.requests[0])
    assert "before the commit" in prompt
    assert "Committed attempt" not in prompt


def test_the_prompt_after_the_commit_carries_the_attempt() -> None:
    prompt = render_coach_prompt(_request())
    assert "Committed attempt:\nWebhooks deliver events" in prompt
    assert "before the commit" not in prompt
```

In `test_the_coach_refuses_forbidden_blocks_and_uncommitted_attempts` (around line 101) delete the second `pytest.raises` block, the one with `_request(committed_attempt="   ")`, and rename the test to `test_the_coach_refuses_forbidden_blocks`. Leave the two `draft_note` raises in the later test alone: the note still needs a commit.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest apps/backend/tests/unit/agents/test_coach_service.py -q`
Expected: failures on `interviewer`, `.phase`, the `phase=` keyword, and the empty-attempt turn.

- [ ] **Step 3: Implement the role changes**

In `apps/backend/src/tamforge_backend/agents/roles/coach.py`:

Replace the module docstring's first rule with:

```python
- It never runs in a block whose `allowed_ai_role` forbids it (`none`, `planner`,
  `reviewer` or `analyst`). Before the learner commits it asks a recall question and
  gives hints on request; a hint is reported in `hint_given` and the caller records
  it as assistance on the attempt. After the commit it corrects.
```

Change the constants and models:

```python
COACHING_ROLES: frozenset[str] = frozenset({"coach", "tutor", "interviewer"})
CoachPhase = Literal["before_commit", "after_commit"]
```

In `CoachTurn` add, after `next_step`:

```python
    hint_given: bool = False
```

In `CoachRequest` add a property at the end of the dataclass:

```python
    @property
    def phase(self) -> CoachPhase:
        return "after_commit" if self.committed_attempt.strip() else "before_commit"
```

Change `validate_coach_turn`:

```python
def validate_coach_turn(
    payload: Mapping[str, object], *, next_step: str, phase: CoachPhase = "after_commit"
) -> tuple[str, ...]:
    """Issues by name; empty means the turn may be shown."""
    try:
        turn = CoachTurn.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "turn"
        return (f"coach turn {location}: {first['msg']}",)
    if turn.next_step.strip() != next_step.strip():
        return ("the next step must be the plan's, not the coach's",)
    if turn.hint_given and phase == "after_commit":
        return ("a hint is recorded only before the commit",)
    lowered = turn.message.lower()
    for marker in ("marked as done", "i marked", "i recorded", "i completed"):
        if marker in lowered:
            return ("the coach cannot claim to have recorded or completed anything",)
    return ()
```

In `CoachService.turn` delete the two lines:

```python
        if not request.committed_attempt.strip():
            raise RoleContractError("the coach speaks only after the learner commits")
```

and change the `prepare_role_prompt` call and the validator lambda:

```python
        prepare_role_prompt(
            AgentRole.COACH,
            committed=request.phase == "after_commit",
            requested_context=(TASK_BRIEF, COMMITTED_ATTEMPT, SELF_REVIEW),
        )
        ...
        runtime = BoundedClaudeRuntime(
            adapter,
            validate=lambda payload: validate_coach_turn(
                payload, next_step=request.next_step, phase=request.phase
            ),
        )
```

`draft_note` keeps its committed-attempt check unchanged.

In `render_coach_prompt` replace the line `"Committed attempt:\n" + request.committed_attempt,` with:

```python
    ]
    if request.phase == "before_commit":
        lines.append(
            "Phase: before the commit. The learner has not committed Attempt A yet. Open with "
            "one recall question for the objective, wait for their attempt, and when they ask "
            "for help give the smallest hint that unblocks them, never the full answer. Set "
            "hint_given to true on any turn that gives a hint; it is recorded as assistance."
        )
    else:
        lines.append("Phase: after the commit.")
        lines.append("Committed attempt:\n" + request.committed_attempt)
    lines_after = [
```

Then keep the rest of the function but make sure `if request.self_review:` and everything after it appends to `lines` as before (rename nothing else; the snippet above only shows where the branch goes: close the initial list at `next_step`, then append the phase lines, then continue with the existing `if request.self_review:` block).

Add `"CoachPhase"` to `__all__`.

In `apps/backend/src/tamforge_backend/agents/sdk_runtime.py` replace `COACH_SYSTEM_PROMPT` with:

```python
COACH_SYSTEM_PROMPT = (
    "You are the TAM Forge coach for one study block. The prompt states the phase. "
    "Before the commit: open with one recall question for the block's objective, wait for "
    "the learner's attempt, and when they ask for help give the smallest hint that unblocks "
    "them, never the full answer; set hint_given to true on every turn that gives a hint. "
    "After the commit: respond to what they wrote, name what is strong, name the gap "
    "against the pass criteria, and give one concrete improvement; hint_given stays false. "
    "Repeat the plan's next step verbatim in next_step; never invent a different one. "
    "Propose at most five short evidence items the learner may record: notes, corrections, "
    "questions, or cards (kind card: text is the question, answer is the answer). Never "
    "claim to have recorded, scored or completed anything. Answer in the learner's "
    "language. Return only the object."
)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest apps/backend/tests/unit/agents/test_coach_service.py apps/backend/tests/unit/agents/test_sdk_runtime.py -q`
Expected: all pass.

- [ ] **Step 5: Lint and types**

Run: `uv run ruff check apps/backend && uv run mypy apps/backend/src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents/roles/coach.py apps/backend/src/tamforge_backend/agents/sdk_runtime.py apps/backend/tests/unit/agents/test_coach_service.py
git commit -m "Teach the coach its phase and let it report hints"
```

---

### Task 3: The coaching thread records assistance before the commit

**Files:**
- Create: `apps/backend/alembic/versions/20260923_0038_coach_assistance.py`
- Modify: `apps/backend/src/tamforge_backend/coaching/models.py` (CoachThread)
- Modify: `apps/backend/src/tamforge_backend/coaching/schemas.py` (CoachThreadResponse)
- Modify: `apps/backend/src/tamforge_backend/coaching/service.py`
- Modify: `apps/backend/tests/unit/coaching/test_routes.py` (`_thread` fixture)
- Modify: `apps/backend/tests/integration/coaching/test_coach_threads.py`
- Regenerate: `apps/macos/TAMForge/openapi.yaml`

**Interfaces:**
- Consumes: `CoachTurn.hint_given`, `CoachRequest.phase` from Task 2.
- Produces: `coach_threads.assistance_mode` column, values `none | coach_preparation | hint_ladder`; `CoachThreadResponse.assistance_mode: str`; `next_step_for` returns `"Write your independent attempt; ask the coach for a hint only when stuck."` before the commit.

- [ ] **Step 1: Write the migration**

Create `apps/backend/alembic/versions/20260923_0038_coach_assistance.py`:

```python
"""Coach threads record the assistance given before the commit."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0038_coach_assistance"
down_revision = "20260923_0037_token_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coach_threads",
        sa.Column("assistance_mode", sa.Text(), nullable=False, server_default="none"),
    )
    op.create_check_constraint(
        "ck_coach_threads_assistance_mode_allowed",
        "coach_threads",
        "assistance_mode IN ('none', 'coach_preparation', 'hint_ladder')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_coach_threads_assistance_mode_allowed", "coach_threads", type_="check"
    )
    op.drop_column("coach_threads", "assistance_mode")
```

- [ ] **Step 2: Add the column to the model**

In `apps/backend/src/tamforge_backend/coaching/models.py`, import `CheckConstraint` from `sqlalchemy` and add to `CoachThread`, after `activity_instance_id`:

```python
    # What the Coach gave before the commit: none, coach_preparation (it spoke) or
    # hint_ladder (it gave at least one hint). It only ever goes up.
    assistance_mode: Mapped[str] = mapped_column(Text, nullable=False, default="none")
```

and add to the class:

```python
    __table_args__ = (
        CheckConstraint(
            "assistance_mode IN ('none', 'coach_preparation', 'hint_ladder')",
            name="ck_coach_threads_assistance_mode_allowed",
        ),
    )
```

- [ ] **Step 3: Extend the response schema**

In `apps/backend/src/tamforge_backend/coaching/schemas.py`, `CoachThreadResponse` gains, after `committed`:

```python
    assistance_mode: Literal["none", "coach_preparation", "hint_ladder"]
```

In `apps/backend/tests/unit/coaching/test_routes.py`, `_thread` passes `assistance_mode="none",` after `committed=True,`.

- [ ] **Step 4: Write the failing integration test changes**

In `apps/backend/tests/integration/coaching/test_coach_threads.py`:

Change `FakeTransport` so a hint can be requested:

```python
class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def respond(self, request: object) -> Mapping[str, object]:
        self.requests.append(request)
        next_step = request.next_step  # type: ignore[attr-defined]
        message = request.learner_message  # type: ignore[attr-defined]
        if request.phase == "before_commit":  # type: ignore[attr-defined]
            return {
                "message": "What does a 200 from the receiver mean for the sender?"
                if "pista" not in message
                else "Think about who owns the retry once the receiver says nothing.",
                "next_step": next_step,
                "hint_given": "pista" in message,
                "proposed_evidence": [],
            }
        return {
            "message": "Your note names delivery but not retries. Add the backoff rule.",
            "next_step": next_step,
            "proposed_evidence": [
                {"kind": "note", "text": "Retries use exponential backoff."},
                {"kind": "card", "text": "What does a 200 mean?", "answer": "Accepted."},
            ],
        }
```

Replace the block that asserts `CoachingConflict, match="commit"` with:

```python
                async with factory() as session:
                    before = await service(session).thread(
                        owner_id=owner_id, activity_id=coached_id
                    )
                    assert before.thread_id is None and before.coaching_allowed
                    assert not before.committed
                    assert before.assistance_mode == "none"
                    assert before.next_step.startswith("Write your independent attempt")
                    opened = await service(session).send(
                        owner_id=owner_id, activity_id=coached_id, text="empiezo"
                    )
                    assert opened.assistance_mode == "coach_preparation"
                    hinted = await service(session).send(
                        owner_id=owner_id, activity_id=coached_id, text="dame una pista"
                    )
                    assert hinted.assistance_mode == "hint_ladder"
                    again = await service(session).send(
                        owner_id=owner_id, activity_id=coached_id, text="ahora sí"
                    )
                    assert again.assistance_mode == "hint_ladder"
                    with pytest.raises(CoachingConflict, match="does not allow"):
                        await service(session).send(
                            owner_id=owner_id, activity_id=forbidden_id, text="hola"
                        )
```

Later in the same test, where the committed thread is sent to, add after the first post-commit `send` assertion:

```python
                    assert after.assistance_mode == "hint_ladder"
```

(`after` is whatever name the existing test gives the post-commit send result; use that name.)

Run: `TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/coaching -q`
Expected: fails on `assistance_mode`. If no database is reachable the test is skipped locally; CI's `backend-integration` job runs it.

- [ ] **Step 5: Implement the service changes**

In `apps/backend/src/tamforge_backend/coaching/service.py`:

Update the module docstring's first line to: `"""Coaching threads: the learner may write before or after committing; the Coach answers in shape.`

Change `next_step_for`:

```python
def next_step_for(activity: ActivityInstance) -> str:
    """The plan's next step, derived from state; the Coach repeats it, never invents it."""
    if activity.output_committed_at is None:
        return "Write your independent attempt; ask the coach for a hint only when stuck."
    if activity.state == "output_committed":
        return "Submit the mandatory self-review for this block."
    if activity.state in {"correction_due", "needs_work"}:
        return "Complete the due correction before moving on."
    return "Continue with the next block of the day."
```

In `send`, delete:

```python
                if loaded.activity.output_committed_at is None:
                    raise CoachingConflict("commit an attempt before asking the coach")
```

After `turn = await self._coach.turn(request)` succeeds and before the messages are added, insert:

```python
                if request.phase == "before_commit":
                    if turn.hint_given:
                        thread.assistance_mode = "hint_ladder"
                    elif thread.assistance_mode == "none":
                        thread.assistance_mode = "coach_preparation"
```

In `_response`, pass `assistance_mode=cast(Any, "none" if loaded.thread is None else loaded.thread.assistance_mode),` after `committed=...`.

- [ ] **Step 6: Regenerate the OpenAPI contract**

Run: `uv run python scripts/ci/check_openapi.py --write && uv run python scripts/ci/check_openapi.py`
Expected: the second command exits 0 and `apps/macos/TAMForge/openapi.yaml` shows `assistance_mode` under `CoachThreadResponse`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest apps/backend/tests/unit/coaching apps/backend/tests/unit/agents -q && uv run ruff check apps/backend && uv run mypy apps/backend/src`
Then the integration test from Step 4 if a database is up.
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/alembic/versions/20260923_0038_coach_assistance.py apps/backend/src/tamforge_backend/coaching apps/backend/tests/unit/coaching/test_routes.py apps/backend/tests/integration/coaching/test_coach_threads.py apps/macos/TAMForge/openapi.yaml
git commit -m "Let the coach answer before the commit and record the help it gave"
```

---

### Task 4: The committed attempt carries the coaching thread's assistance

**Files:**
- Modify: `apps/backend/src/tamforge_backend/learning/service.py:785-795`
- Test: `apps/backend/tests/integration/coaching/test_coach_threads.py` (one assertion)

**Interfaces:**
- Consumes: `CoachThread.assistance_mode` from Task 3.
- Produces: `Attempt.assistance_mode` equals the stronger of the activity's mode and the thread's mode; helper `_coached_assistance(owner_id, activity_id) -> str` in `ActivityService`.

- [ ] **Step 1: Write the failing assertion**

In `apps/backend/tests/integration/coaching/test_coach_threads.py`, the existing test commits the attempt by hand with `Attempt(... assistance_mode="none" ...)`, which bypasses the service. Add a second integration test at the bottom of the file that commits through the service:

```python
@pytest.mark.integration
def test_the_committed_attempt_carries_the_thread_assistance(test_database_url: str) -> None:
    """A hint given before the commit lands on the attempt the learning service writes."""
    from sqlalchemy import select
    from tamforge_backend.coaching.models import CoachThread
    from tamforge_backend.learning.models import ActivityInstance, Attempt

    # Reuse the fixture flow of the first test up to `coached_id` (copy the setup that
    # imports the roadmap, activates it, sets the start date and ensures the day; do not
    # share state between the two tests). Then:
    #   1. send "dame una pista" through CoachThreadService so the thread reads hint_ladder
    #   2. start the activity and commit a writing output through ActivityService
    #      (see apps/backend/tests/integration/foundation/test_month1_workspace.py for a
    #      complete commit_output call with a valid writing output and no artifacts)
    #   3. assert the Attempt row for the activity has assistance_mode == "hint_ladder"
    #      and the CoachThread row still reads "hint_ladder"
```

Write the test body in full following that outline; the foundation test shows the exact `commit_output` arguments and a valid output payload.

- [ ] **Step 2: Run it to see it fail**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/coaching -q -k carries`
Expected: fails with `assistance_mode == "none"`.

- [ ] **Step 3: Implement**

In `apps/backend/src/tamforge_backend/learning/service.py` add the import `from ..coaching.models import CoachThread` next to the other `..` imports, and add this method to `ActivityService` near `_load_commitment_artifacts`:

```python
    _ASSISTANCE_RANK = {"none": 0, "coach_preparation": 1, "hint_ladder": 2}

    async def _coached_assistance(self, *, owner_id: int, activity_id: int, current: str) -> str:
        """The stronger of the activity's own mode and what the coach gave before the commit."""
        coached = await self._session.scalar(
            select(CoachThread.assistance_mode)
            .where(CoachThread.owner_id == owner_id)
            .where(CoachThread.activity_instance_id == activity_id)
        )
        if coached is None:
            return current
        rank = self._ASSISTANCE_RANK
        return coached if rank.get(coached, 0) > rank.get(current, 0) else current
```

In `commit_output`, replace `assistance_mode=row.activity.assistance_mode,` in the `Attempt(...)` constructor with:

```python
                    assistance_mode=await self._coached_assistance(
                        owner_id=owner_id,
                        activity_id=activity_id,
                        current=row.activity.assistance_mode,
                    ),
```

- [ ] **Step 4: Run tests, lint, types**

Run: `uv run pytest apps/backend/tests/unit/learning -q && uv run ruff check apps/backend && uv run mypy apps/backend/src`
Then the integration test from Step 2.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/tamforge_backend/learning/service.py apps/backend/tests/integration/coaching/test_coach_threads.py
git commit -m "Carry the coach's pre-commit assistance onto the committed attempt"
```

---

### Task 5: TaskGuide, the step list and the current step (macOS, logic only)

**Files:**
- Create: `apps/macos/TAMForge/Features/Activities/TaskGuide.swift`
- Create: `apps/macos/TAMForgeTests/TaskGuideTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Produces: `enum TaskGuide { static func steps(for block: ActivityBlock) -> [String]; static func currentStep(for activity: ActivityDetail) -> Int? }`.

- [ ] **Step 1: Write the failing tests**

Create `apps/macos/TAMForgeTests/TaskGuideTests.swift`:

```swift
import XCTest

final class TaskGuideTests: XCTestCase {
    private func detail(block: ActivityBlock, state: ActivityState, sourceHidden: Bool = false) -> ActivityDetail {
        var detail = ActivityFixtures.detail(state: state)
        detail.taskContract.block = block
        detail.sourceHidden = sourceHidden
        return detail
    }

    func testEveryBlockHasStepsThatEndInCommitOrLater() {
        for block in ActivityBlock.allCases {
            let steps = TaskGuide.steps(for: block)
            XCTAssertFalse(steps.isEmpty, "\(block) has no steps")
            XCTAssertTrue(steps.contains("Commit"), "\(block) never commits")
        }
    }

    func testTheInterviewBlockListsTheCoachedCycle() {
        XCTAssertEqual(
            TaskGuide.steps(for: .communicationSpoken),
            ["Read the question", "Independent Attempt A, written or recorded", "Commit", "Self-review", "Coach: two corrections"]
        )
    }

    func testBeforeTheCommitTheAttemptStepIsCurrent() {
        for state in [ActivityState.ready, .active, .paused] {
            XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .communicationSpoken, state: state)), 1)
        }
    }

    func testTechnicalLearningPointsAtHidingTheSourceUntilItIsHidden() {
        XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .technicalLearning, state: .active)), 1)
        XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .technicalLearning, state: .active, sourceHidden: true)), 2)
    }

    func testAfterTheCommitTheSelfReviewIsCurrent() {
        let steps = TaskGuide.steps(for: .sql)
        XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .sql, state: .outputCommitted)), steps.firstIndex(of: "Self-review"))
    }

    func testAfterTheSelfReviewTheCoachOrTheLastStepIsCurrent() {
        for state in [ActivityState.selfReviewComplete, .aiProcessing, .feedbackReady, .correctionDue, .demonstrated, .needsWork] {
            XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .tamCase, state: state)), 5, "\(state)")
            XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .careerPipeline, state: state)), 4, "\(state)")
        }
    }

    func testIncompleteAndSupersededHaveNoCurrentStep() {
        XCTAssertNil(TaskGuide.currentStep(for: detail(block: .sql, state: .incomplete)))
        XCTAssertNil(TaskGuide.currentStep(for: detail(block: .sql, state: .superseded)))
    }
}
```

- [ ] **Step 2: Create the implementation**

Create `apps/macos/TAMForge/Features/Activities/TaskGuide.swift`:

```swift
import Foundation

/// The block's steps, spelled out from its procedure, and which one the learner is on.
/// Nothing here comes from the AI: the list is the block type's contract and the
/// current step is read off the activity state.
enum TaskGuide {
    private struct Plan {
        let steps: [String]
        let attempt: Int
        let coach: Int?
    }

    private static func plan(for block: ActivityBlock) -> Plan {
        switch block {
        case .communicationSpoken:
            Plan(steps: ["Read the question", "Independent Attempt A, written or recorded", "Commit", "Self-review", "Coach: two corrections"], attempt: 1, coach: 4)
        case .technicalLearning:
            Plan(steps: ["Read the source", "Hide the source", "Recall attempt", "Commit", "Self-review", "Coach and note"], attempt: 2, coach: 5)
        case .sql:
            Plan(steps: ["Read the problem", "Query and run", "Explain and business meaning", "Commit", "Self-review", "Coach"], attempt: 1, coach: 5)
        case .tamCase:
            Plan(steps: ["Read the prompt", "Discovery and assumptions", "Final artifact", "Commit", "Self-review", "Coach"], attempt: 1, coach: 5)
        case .careerPipeline:
            Plan(steps: ["Pick the action", "Do it", "Record it", "Commit", "Self-review"], attempt: 1, coach: nil)
        case .correctionWarmup:
            Plan(steps: ["Read the correction", "Attempt", "Commit", "Self-review"], attempt: 1, coach: nil)
        case .dailyClose:
            Plan(steps: ["Outputs and actual time, 5 min", "Recall items, 5 min", "Competency evidence, 3 min", "Exact next action, 2 min", "Commit", "Self-review"], attempt: 0, coach: nil)
        case .saturdayAssessment:
            Plan(steps: ["Read the prompt", "Independent attempt, no AI", "Commit", "Self-review"], attempt: 1, coach: nil)
        }
    }

    static func steps(for block: ActivityBlock) -> [String] {
        plan(for: block).steps
    }

    static func currentStep(for activity: ActivityDetail) -> Int? {
        let block = activity.taskContract.block
        let plan = plan(for: block)
        switch activity.state {
        case .ready, .active, .paused:
            if block == .technicalLearning, !activity.sourceHidden { return plan.attempt - 1 }
            return plan.attempt
        case .outputCommitted:
            return plan.steps.firstIndex(of: "Self-review")
        case .selfReviewComplete, .aiProcessing, .feedbackReady, .correctionDue, .demonstrated, .needsWork:
            return plan.coach ?? plan.steps.count - 1
        case .incomplete, .superseded:
            return nil
        }
    }
}
```

- [ ] **Step 3: Wire both files into the Xcode project**

Edit `apps/macos/TAMForge.xcodeproj/project.pbxproj`, following the `TodayTaskStatus.swift` / `TodayTaskStatusTests.swift` entries as the template (ids `D5000000000000000000000A`, `D5000000000000000000000B`, build files `D5000000000000000000001E`, `D5000000000000000000001F`, `D50000000000000000000020`). Use fresh ids `FE000000000000000000010A` (TaskGuide.swift file ref), `FE000000000000000000010B` (TaskGuideTests.swift file ref), `FE00000000000000000001AE` and `FE00000000000000000001AF` (TaskGuide.swift build files, app Sources and unit-test Sources), `FE00000000000000000001B0` (TaskGuideTests.swift build file). Add:

1. Two `PBXFileReference` lines next to line 437-438.
2. Three `PBXBuildFile` lines next to lines 251-253.
3. `TaskGuide.swift` into the `Activities` group (`E20000000000000000000093`, the children list around line 761-775) and `TaskGuideTests.swift` into the `TAMForgeTests` group (`A10000000000000000000044`, around line 501-546).
4. `TaskGuide.swift in Sources` into app Sources `A10000000000000000000091` (near line 1126) and unit-test Sources `A10000000000000000000092` (near line 1265); `TaskGuideTests.swift in Sources` into unit-test Sources (near line 1266).

Run: `plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj`
Expected: `OK`.

- [ ] **Step 4: Run the unit tests**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests/TaskGuideTests test 2>&1 | tail -30`
Expected: `TEST SUCCEEDED` with 7 tests executed.

- [ ] **Step 5: Commit**

```bash
git add apps/macos/TAMForge/Features/Activities/TaskGuide.swift apps/macos/TAMForgeTests/TaskGuideTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "Derive the activity's step list and current step from its block and state"
```

---

### Task 6: The guide panel and the always-present Coach (macOS UI)

**Files:**
- Modify: `apps/macos/TAMForge/Features/Activities/TaskGuide.swift` (add the panel view)
- Modify: `apps/macos/TAMForge/Features/Activities/ActivityWorkspaceView.swift:116-170`
- Modify: `apps/macos/TAMForge/Features/Coaching/CoachModels.swift`
- Modify: `apps/macos/TAMForge/Features/Coaching/CoachThreadModel.swift`
- Modify: `apps/macos/TAMForge/Features/Coaching/CoachPanel.swift`
- Test: `apps/macos/TAMForgeTests/CoachThreadModelTests.swift`

**Interfaces:**
- Consumes: `TaskGuide` from Task 5; `assistance_mode` in the thread JSON from Task 3.
- Produces: `struct TaskGuidePanel: View` with identifiers `activityTaskGuide` and `activityTaskGuideStep`; `CoachThread.assistanceMode: String?`; `CoachThreadModel.canSend` no longer needs `committed`.

- [ ] **Step 1: Write the failing model tests**

In `apps/macos/TAMForgeTests/CoachThreadModelTests.swift` change the private `thread(allowed:)` helper to accept `committed: Bool = true` and pass it through, adding `assistanceMode: "none"` to the initializer call, and add:

```swift
    func testTheCoachCanBeAskedBeforeTheCommit() async {
        let api = FakeCoachAPI(thread: thread(allowed: true, committed: false))
        let model = CoachThreadModel(activityID: 41, api: api)
        await model.open()
        model.draft = "what should I recall first?"

        XCTAssertTrue(model.canSend)
    }

    func testAThreadWithoutAssistanceModeStillDecodes() throws {
        let json = """
        {"activity_id": 41, "thread_id": null, "coaching_allowed": true, "committed": false,
         "next_step": "Write your independent attempt.", "messages": []}
        """
        let thread = try JSONDecoder().decode(CoachThread.self, from: Data(json.utf8))
        XCTAssertNil(thread.assistanceMode)
    }
```

Also update the stub in `FakeCoachAPI` and any other `CoachThread(` initializer in the tests to include `assistanceMode:`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests/CoachThreadModelTests test 2>&1 | tail -30`
Expected: compile error on `assistanceMode`.

- [ ] **Step 3: Update the models**

In `apps/macos/TAMForge/Features/Coaching/CoachModels.swift`, `CoachThread` gains `let assistanceMode: String?` after `nextStep`, with `case assistanceMode = "assistance_mode"` in `CodingKeys`. Change the `notAllowed` message to `"This block is sealed: no coaching."`.

In `apps/macos/TAMForge/Features/Coaching/CoachThreadModel.swift`:

```swift
    var canSend: Bool {
        guard let thread, thread.coachingAllowed, !isBusy else { return false }
        return !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
```

and in `perform`'s `.notAllowed` fallback pass `assistanceMode: nil`.

Update the header comment of `CoachThreadModel` and `CoachPanel` to say the coach is available before and after the commit.

- [ ] **Step 4: Update the Coach panel copy**

In `apps/macos/TAMForge/Features/Coaching/CoachPanel.swift`, the idle text becomes:

```swift
                    Text("Start with the coach: it asks a recall question first and gives hints only when you ask. Help before the commit is recorded as assistance.")
                        .organic(.small)
```

In `conversation(_:)`, before the `ForEach(thread.messages)`, add:

```swift
        if let mode = thread.assistanceMode, mode != "none" {
            Label("Recorded as assisted: \(mode.replacingOccurrences(of: "_", with: " "))", systemImage: "hand.raised")
                .organic(.small, color: Organic.Color.warning)
                .accessibilityIdentifier("coachAssistanceMode")
        }
```

- [ ] **Step 5: Add the guide panel view**

Append to `apps/macos/TAMForge/Features/Activities/TaskGuide.swift`:

```swift
import SwiftUI

/// The step list at the top of the activity screen. Rows are plain text; the current
/// row carries the status dot and the `activityTaskGuideStep` identifier.
struct TaskGuidePanel: View {
    let activity: ActivityDetail

    var body: some View {
        let steps = TaskGuide.steps(for: activity.taskContract.block)
        let current = TaskGuide.currentStep(for: activity)
        GroupBox("Your steps") {
            VStack(alignment: .leading, spacing: Organic.Space.p8) {
                ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                    HStack(alignment: .firstTextBaseline, spacing: Organic.Space.p8) {
                        OrganicStatusDot(color: dotColor(index: index, current: current))
                        Text("\(index + 1). \(step)")
                            .font(Organic.Font.figtree(index == current ? .semibold : .regular, size: 13))
                            .foregroundStyle(index == current ? Organic.Color.text : Organic.Color.muted)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier(index == current ? "activityTaskGuideStep" : "activityTaskGuideRow\(index)")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("activityTaskGuide")
    }

    private func dotColor(index: Int, current: Int?) -> Color {
        guard let current else { return Organic.Color.faint }
        if index < current { return Organic.Color.accent2_300 }
        if index == current { return Organic.Color.accent300 }
        return Organic.Color.faint
    }
}
```

`GroupBox` is what every other panel on this screen uses, so the guide matches them. `OrganicStatusDot(color:)` and the four color names (`text`, `muted`, `faint`, `accent2_300`, `accent300`) exist in `OrganicTokens.swift` and `OrganicComponents.swift`; do not add literals.

- [ ] **Step 6: Place the panel and free the Coach**

In `apps/macos/TAMForge/Features/Activities/ActivityWorkspaceView.swift`:

In `mainColumn`, right after `header(activity)`:

```swift
            TaskGuidePanel(activity: activity)
```

Delete the three lines:

```swift
            Label("AI feedback remains unavailable until a server-backed self-review. This app cannot create an AI Attempt A.", systemImage: "lock")
                .organic(.small)
                .accessibilityLabel("AI feedback locked until self-review")
```

In `rail`, change the coach block so the Coach shows in every state and the note keeps its post-commit gate:

```swift
            if let coach { CoachPanel(model: coach) }
            if !activity.state.isEditable {
                if let note { StudyNotePanel(model: note) }
            }
```

- [ ] **Step 7: Build and run the unit tests**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests test 2>&1 | grep -E "Executed|error:|TEST" | tail -10`
Expected: `TEST SUCCEEDED`, executed count above 0, no `error:` lines.

Run: `git diff --stat origin/main -- apps/macos/TAMForgeUITests/` and `grep -rn "LazyVStack(\|LazyHStack(\|LazyVGrid(" apps/macos/TAMForge/`
Expected: both empty.

- [ ] **Step 8: Commit**

```bash
git add apps/macos/TAMForge/Features/Activities/TaskGuide.swift apps/macos/TAMForge/Features/Activities/ActivityWorkspaceView.swift apps/macos/TAMForge/Features/Coaching apps/macos/TAMForgeTests/CoachThreadModelTests.swift
git commit -m "Show the task's steps and open the coach before the commit"
```

---

## Verification gate (after all tasks)

Run, in this order, from the repo root:

```bash
uv sync --all-packages --all-extras --frozen
uv run ruff check .
uv run mypy apps/backend/src packages/protocol/src
uv run pytest apps/backend/tests/acceptance apps/backend/tests/unit apps/backend/tests/security apps/backend/tests/recordings apps/backend/tests/jobs apps/backend/tests/speech apps/backend/tests/evaluation apps/backend/tests/evals packages/protocol/tests infra/tests scripts/ci/tests scripts/dev/tests scripts/github/tests -m "not integration" -q
uv run python scripts/ci/check_openapi.py
uv run python scripts/ci/check_repository_policy.py
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests test
```

If a local `tamforge_test` database is reachable:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run alembic -c apps/backend/alembic.ini upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest -m integration apps/backend/tests/integration/coaching -q
```

Otherwise CI's `backend-integration` job is the gate for Tasks 3 and 4.
