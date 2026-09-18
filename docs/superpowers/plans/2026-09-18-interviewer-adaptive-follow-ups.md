# Interviewer Adaptive Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each free-practice answer the Interviewer may ask up to two short follow-ups generated from the local transcript, the learner can switch that off, and the practice review grades how each follow-up was handled.

**Architecture:** The Mac waits for the local Whisper transcript of the answer it just recorded (bounded by a 45 s timeout), posts it to a new synchronous endpoint `POST /api/v1/practice-answers/follow-up`, and feeds the reply into the existing `InterviewerTurn.askFollowUp(_:)`. The endpoint runs a new tool-less role `interview_follow_up` through the same `BoundedClaudeRuntime` + validator pattern as `practice_review`. Each follow-up answer is its own recording and its own `practice_answers` row linked to the answer it followed by two nullable columns; the review of a linked row gets the earlier question and transcript as context and scores a fourth dimension, `follow_up_handling`.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, Claude Agent SDK behind `AgentSdkRuntime`, pytest; SwiftUI on macOS 15, Swift 6 strict concurrency, XCTest, a hand-maintained `project.pbxproj`.

**Spec:** GitHub issue #390.

## Global Constraints

- TDD: every task writes the failing test first, watches it fail for the stated reason, then writes the minimal code.
- Alembic revision ids are 32 characters or fewer (`alembic_version.version_num` is `varchar(32)`); this plan uses `20260918_0035_follow_ups` (24).
- A Pydantic field that defaults to a bare `None` breaks the Swift contract generator; optional request fields are declared `Annotated[T | None, Field(default=None, ...)]` exactly like `PracticeAnswerCommand.reference_material_id`, and optional response fields are required-nullable (`T | None`, no default) like `PracticeAnswerResponse.readiness`.
- No realistic-looking token, key or secret in any test or fixture; the secret-scan job reads fixtures.
- No new Swift files: `project.pbxproj` uses explicit file references, so every Swift change in this plan lands in a file that is already wired in.
- SwiftUI changes follow `.claude/skills/macos-organic-ui/SKILL.md`: new text uses `Organic.Font.figtree` and `Organic.Color.*`, no existing `accessibilityIdentifier` is renamed or dropped, no lazy stacks, and `git diff --stat origin/main -- apps/macos/TAMForgeUITests/` stays empty.
- XCUITests are never run locally (they take over the desktop); only `-only-testing:TAMForgeTests` runs on this Mac. The `native-ui` CI job covers the UI suite.
- Backend tests: run `~/.local/bin/uv sync --all-packages --all-extras --frozen` once first, then `~/.local/bin/uv run pytest ...`; never pipe pytest into another command, the pipe masks its exit code.
- A test that needs PostgreSQL lives under `apps/backend/tests/integration/` and carries `pytest.mark.integration`; run it against your own container and `TEST_DATABASE_URL`, not the shared port.
- Python: `ruff` line length is 100, `mypy` is strict. Swift: `SWIFT_STRICT_CONCURRENCY = complete`, Swift 6.
- Commits are conventional commits in English and every message ends with the line `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- The interviewer never interrupts: a follow-up is only ever requested after `commitAnswer()`, and `InterviewerTurn` already refuses to speak in any other phase.

## Commands CI runs (the verify gate mirrors these)

From `.github/workflows/ci.yml`, run from the repository root:

```bash
# backend-unit
uv sync --all-packages --all-extras --frozen
uv run ruff check .
uv run python scripts/ci/check_recording_verification.py docs/project/recording-verification-v1.json
uv run mypy apps/backend/src packages/protocol/src
MYPYPATH=apps/backend/src:packages/protocol/src uv run mypy scripts/ci/check_openapi.py scripts/ci/check_repository_policy.py scripts/ci/verify_bootstrap.py scripts/ci/verify_compose.py scripts/dev/seed_foundation_demo.py
uv run python -m scripts.ci.verify_bootstrap
uv run pytest apps/backend/tests/acceptance apps/backend/tests/unit apps/backend/tests/security apps/backend/tests/recordings apps/backend/tests/jobs apps/backend/tests/speech apps/backend/tests/evaluation apps/backend/tests/evals packages/protocol/tests infra/tests scripts/ci/tests scripts/dev/tests scripts/github/tests -m "not integration" -q

# backend-integration (needs PostgreSQL and MinIO; see the workflow for the services)
uv run alembic -c apps/backend/alembic.ini upgrade head
uv run pytest -m "integration and not postgres_integration" apps/backend/tests/integration -q
scripts/run-plan-03-integration.sh apps/backend/tests/integration/agents

# e2e
uv run pytest -m integration apps/backend/tests/integration/foundation/test_month1_workspace.py -q

# openapi
uv run python scripts/ci/check_openapi.py

# secret-scan
uv run python scripts/ci/check_repository_policy.py

# macos-native
scripts/dev/fetch_whisper_framework.sh
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests -retry-tests-on-failure -test-iterations 3 test
xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -configuration Release -destination 'platform=macOS' -derivedDataPath "$RUNNER_TEMP/TAMForgeRelease" CODE_SIGN_IDENTITY=- CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual build
python3 scripts/ci/check_native_bundle.py "$RUNNER_TEMP/TAMForgeRelease/Build/Products/Release/TAMForge.app" --require-ad-hoc

# native-ui (CI only, never locally)
xcodebuild ... -only-testing:TAMForgeUITests -skip-testing:TAMForgeUITests/TAMForgeUITests/testLocalNativeResourceReceipt ... test
python3 scripts/ci/check_native_xcresult.py "$RUNNER_TEMP/TAMForgeUITests.xcresult"
```

The issue's own verification command is `uv run pytest apps/backend/tests -q -k practice`.

## Task order

| Task | Tree | Depends on | Independent of |
|---|---|---|---|
| 1. Role `interview_follow_up` + SDK transport | backend | none | 3, 5, 6 |
| 2. Endpoint `POST /api/v1/practice-answers/follow-up` | backend | 1 | 4, 5, 6 |
| 3. Follow-up columns + `follow_up_handling` review dimension | backend | none (but edits the same `practice/` files as 2: run after 2) | 1, 4, 5, 6 |
| 4. Eval for the follow-up role | backend | 1 | 2, 3, 5, 6 |
| 5. `InterviewPracticeModel` wiring | macOS | none | 1, 2, 3, 4 |
| 6. Service call, submission and the SwiftUI switch | macOS | 5 | 1, 2, 3, 4 |
| 7. Contract regeneration | both | 2, 3 | 4, 5, 6 |

The wire contract Tasks 5 and 6 code against is fixed here, so the macOS tasks never wait for the backend:

```
POST /api/v1/practice-answers/follow-up
  request  {"question": str, "reference_answer": str, "transcript": str, "prior_follow_ups": [str]}
  200      {"follow_up": str | null, "reason": "weak_point" | "pressure_probe" | null}
  422      problem, code practice_invalid     (answer too short, blank question)
  503      problem, code practice_unavailable (Claude disabled, runtime or validator failure)

POST /api/v1/practice-answers   (two new optional fields, both or neither)
  {"question", "recording_id", "reference_material_id"?, "follow_up_question"?, "follow_up_of_recording_id"?}
  response gains "follow_up_of": int | null and "follow_up_question": str | null
```

---

## Task 1: Role `interview_follow_up` and its SDK transport

**Files**
- Create: `apps/backend/src/tamforge_backend/agents/roles/interview_follow_up.py`
- Modify: `apps/backend/src/tamforge_backend/agents/sdk_runtime.py`
- Test (create): `apps/backend/tests/unit/agents/test_interview_follow_up_service.py`
- Test (modify): `apps/backend/tests/unit/agents/test_sdk_runtime.py`

**Interfaces**
- Consumes: `BoundedClaudeRuntime`, `PreparedAgentRun`, `TransportResult`, `AgentOutputInvalid`, `AgentRuntimeError` from `agents/runtime.py`; `RoleContractError` from `agents/roles/contracts.py`; `AgentSdkRuntime._structured`.
- Produces:
  - `FollowUpRequest(question: str, answer_transcript: str, reference_answer: str = "", prior_follow_ups: tuple[str, ...] = (), repair_errors: tuple[str, ...] = ())`
  - `FollowUpOutcome(follow_up: str | None, reason: Literal["weak_point", "pressure_probe"] | None)`, `NO_FOLLOW_UP`
  - `FollowUpTransport.follow_up(request: FollowUpRequest) -> Mapping[str, object]`
  - `InterviewFollowUpService(transport: FollowUpTransport | None, *, model: str).decide(request) -> FollowUpOutcome`
  - `InterviewFollowUpUnavailable(RoleContractError)`
  - `validate_follow_up(payload, *, answer_transcript: str, prior_follow_ups: tuple[str, ...] = ()) -> tuple[str, ...]`
  - `pressure_probe_allowed(question: str, answer_transcript: str) -> bool`
  - `follow_up_schema()`, `render_follow_up_prompt(request)`
  - constants `INTERVIEW_FOLLOW_UP_PROMPT_KEY = "tamforge.interview_follow_up"`, `INTERVIEW_FOLLOW_UP_PROMPT_VERSION = "v1"`, `INTERVIEW_FOLLOW_UP_SCHEMA_ID = "urn:tamforge:schema:interview-follow-up-v1"`, `MAX_FOLLOW_UPS = 2`
  - `AgentSdkRuntime.follow_up(request: FollowUpRequest) -> Mapping[str, object]`

**Independent of:** Tasks 3, 5, 6.

Design notes the implementer needs:
- "Targets something actually said" is enforced by the validator, not trusted to the model: the follow-up must share at least one content word (five letters or more, not in a short stop list) with the transcript. A follow-up whose only anchor is in the reference answer is refused.
- "Pressure probes on a minority of good answers" is enforced by the role, not trusted to the model: `pressure_probe_allowed` opens for about one answer in three, decided by a hash of the question and the transcript, and a `pressure_probe` reply on a closed gate becomes "no follow-up". The prompt tells the model which case it is in.
- `ROLE_CONTRACTS` is not touched. `tests/unit/agents/roles/test_planner.py` asserts `AgentRole.INTERVIEWER not in ROLE_CONTRACTS`, and `practice_review` already pins its prompt version and schema id through `PreparedAgentRun`; this role does the same.

- [ ] **Step 1: Write the failing role test.** Create `apps/backend/tests/unit/agents/test_interview_follow_up_service.py`:

```python
"""The follow-up role: one short question about what was said, or nothing."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from tamforge_backend.agents.roles.contracts import RoleContractError
from tamforge_backend.agents.roles.interview_follow_up import (
    INTERVIEW_FOLLOW_UP_PROMPT_VERSION,
    INTERVIEW_FOLLOW_UP_SCHEMA_ID,
    NO_FOLLOW_UP,
    FollowUpRequest,
    InterviewFollowUpService,
    InterviewFollowUpUnavailable,
    follow_up_schema,
    pressure_probe_allowed,
    render_follow_up_prompt,
    validate_follow_up,
)

QUESTION = "Why are you leaving DataNest?"
ANSWER = (
    "I spent four years building DataNest from zero to twenty five customers and I loved "
    "the customer side. I hit the ceiling of what I can learn there, so I want to do it at scale."
)
# The probe gate is open for QUESTION/ANSWER and closed for this pair (see the gate test).
SOLID_QUESTION = "How do you prioritise competing requests?"
SOLID_ANSWER = (
    "I rank requests by revenue at risk and effort. Last quarter I had five open asks, I "
    "shipped the two that protected ninety thousand dollars in renewals and told the other "
    "three customers a date."
)
WEAK = {"follow_up": "What exactly was the ceiling you hit?", "reason": "weak_point"}


def test_a_short_question_about_what_was_said_or_nothing_passes() -> None:
    assert validate_follow_up(WEAK, answer_transcript=ANSWER) == ()
    assert validate_follow_up({"follow_up": None, "reason": None}, answer_transcript=ANSWER) == ()
    assert INTERVIEW_FOLLOW_UP_PROMPT_VERSION == "v1"
    assert INTERVIEW_FOLLOW_UP_SCHEMA_ID == "urn:tamforge:schema:interview-follow-up-v1"
    assert set(follow_up_schema()["required"]) == {"follow_up", "reason"}  # type: ignore[arg-type]


def test_invented_targets_double_questions_repeats_and_long_ones_are_refused() -> None:
    def issue(payload: Mapping[str, object], prior: tuple[str, ...] = ()) -> str:
        return validate_follow_up(payload, answer_transcript=ANSWER, prior_follow_ups=prior)[0]

    assert "both" in issue({"follow_up": None, "reason": "weak_point"})
    invented = {"follow_up": "How large was the Kubernetes migration budget?"}
    assert "actually said" in issue({**invented, "reason": "weak_point"})
    double = {"follow_up": "What was the ceiling? Who set it?", "reason": "weak_point"}
    assert "one spoken question" in issue(double)
    assert "already asked" in issue(WEAK, ("what exactly was the ceiling you hit",))
    wordy = {"follow_up": "What " + "so " * 31 + "was the ceiling?", "reason": "weak_point"}
    assert "at most 30 words" in issue(wordy)
    assert issue({"follow_up": "x" * 241 + "?", "reason": "weak_point"}).startswith("follow-up ")
    assert issue({**WEAK, "reason": "curiosity"}).startswith("follow-up reason")


def test_the_probe_gate_is_stable_and_the_prompt_says_which_case_it_is() -> None:
    assert pressure_probe_allowed(QUESTION, ANSWER) is True
    assert pressure_probe_allowed(SOLID_QUESTION, SOLID_ANSWER) is False
    request = FollowUpRequest(
        question=QUESTION,
        answer_transcript=ANSWER,
        reference_answer="Four anchors.",
        prior_follow_ups=("Why now?",),
        repair_errors=("one question only",),
    )
    prompt = render_follow_up_prompt(request)
    assert "Question asked: Why are you leaving DataNest?" in prompt and ANSWER in prompt
    assert "- Why now?" in prompt and "not something they said" in prompt
    assert "pressure probe" in prompt and "fix these:" in prompt
    closed = render_follow_up_prompt(
        FollowUpRequest(question=SOLID_QUESTION, answer_transcript=SOLID_ANSWER)
    )
    assert "ask nothing" in closed and "pressure probe" not in closed


class _Transport:
    def __init__(self, payloads: list[Mapping[str, object]]) -> None:
        self.payloads = payloads
        self.requests: list[FollowUpRequest] = []

    async def follow_up(self, request: FollowUpRequest) -> Mapping[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


def test_the_service_repairs_once_and_refuses_what_it_cannot_read() -> None:
    transport = _Transport([{"follow_up": "bad", "reason": "weak_point"}, dict(WEAK)])
    service = InterviewFollowUpService(transport, model="claude-fable-5-1")
    request = FollowUpRequest(question=QUESTION, answer_transcript=ANSWER)
    outcome = asyncio.run(service.decide(request))
    assert outcome.follow_up == WEAK["follow_up"] and outcome.reason == "weak_point"
    assert len(transport.requests) == 2 and transport.requests[1].repair_errors

    with pytest.raises(RoleContractError):
        asyncio.run(service.decide(FollowUpRequest(question=QUESTION, answer_transcript="Yes.")))
    with pytest.raises(RoleContractError):
        asyncio.run(service.decide(FollowUpRequest(question="  ", answer_transcript=ANSWER)))
    with pytest.raises(InterviewFollowUpUnavailable):
        asyncio.run(
            InterviewFollowUpService(None, model="m").decide(
                FollowUpRequest(question=QUESTION, answer_transcript=ANSWER)
            )
        )
    stubborn = _Transport([{"follow_up": "bad", "reason": "weak_point"}] * 2)
    with pytest.raises(InterviewFollowUpUnavailable):
        asyncio.run(
            InterviewFollowUpService(stubborn, model="m").decide(
                FollowUpRequest(question=QUESTION, answer_transcript=ANSWER)
            )
        )


def test_two_follow_ups_end_it_without_a_model_call_and_probes_obey_the_gate() -> None:
    idle = _Transport([])
    done = FollowUpRequest(
        question=QUESTION, answer_transcript=ANSWER, prior_follow_ups=("Why now?", "Why us?")
    )
    assert asyncio.run(InterviewFollowUpService(idle, model="m").decide(done)) == NO_FOLLOW_UP
    assert idle.requests == []

    probe = {"follow_up": "What would you do if the customers left?", "reason": "pressure_probe"}
    opened = InterviewFollowUpService(_Transport([dict(probe)]), model="m")
    kept = asyncio.run(opened.decide(FollowUpRequest(question=QUESTION, answer_transcript=ANSWER)))
    assert kept.reason == "pressure_probe"

    gated = {"follow_up": "How did you decide which renewals mattered?", "reason": "pressure_probe"}
    closed = InterviewFollowUpService(_Transport([gated]), model="m")
    dropped = asyncio.run(
        closed.decide(FollowUpRequest(question=SOLID_QUESTION, answer_transcript=SOLID_ANSWER))
    )
    assert dropped == NO_FOLLOW_UP
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/agents/test_interview_follow_up_service.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tamforge_backend.agents.roles.interview_follow_up'`.

- [ ] **Step 3: Write the role.** Create `apps/backend/src/tamforge_backend/agents/roles/interview_follow_up.py`:

```python
"""The interviewer's follow-up: at most one short spoken question about the answer just given.

The learner answered a practice question aloud and the Mac transcribed it. One bounded,
tool-less read decides whether a real interviewer would follow up: on a weak point (a vague
claim, a missing number, an assertion with no example) or, on a minority of solid answers,
as a pressure probe, so a follow-up never comes to mean "I answered badly". The follow-up
must reuse something the learner actually said. The interviewer never coaches.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..runtime import (
    AgentOutputInvalid,
    AgentRuntimeError,
    BoundedClaudeRuntime,
    PreparedAgentRun,
    TransportResult,
)
from .contracts import RoleContractError

INTERVIEW_FOLLOW_UP_PROMPT_KEY = "tamforge.interview_follow_up"
INTERVIEW_FOLLOW_UP_PROMPT_VERSION = "v1"
INTERVIEW_FOLLOW_UP_SCHEMA_ID = "urn:tamforge:schema:interview-follow-up-v1"
INTERVIEW_FOLLOW_UP_JOB_TYPE = "claude.interview_follow_up"
INTERVIEW_FOLLOW_UP_MAX_TURNS = 4
# The learner is waiting in front of the Mac; the app gives up at 45 seconds overall.
INTERVIEW_FOLLOW_UP_WALL_TIME_SECONDS = 30.0
MAX_FOLLOW_UPS = 2
MAX_FOLLOW_UP_CHARS = 240
MAX_FOLLOW_UP_WORDS = 30
MINIMUM_ANSWER_WORDS = 8
MAX_ANSWER_CHARS = 40_000
# A solid answer is probed about one time in three, decided by the answer itself so the
# same answer always gets the same treatment and the share stays a minority.
PRESSURE_PROBE_ONE_IN = 3
_COMMON_WORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "because",
        "before",
        "could",
        "every",
        "going",
        "really",
        "should",
        "something",
        "their",
        "there",
        "these",
        "thing",
        "things",
        "think",
        "those",
        "through",
        "where",
        "which",
        "while",
        "would",
        "years",
    }
)

FollowUpReason = Literal["weak_point", "pressure_probe"]


class InterviewFollowUpUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the session moves on without a follow-up."""


@dataclass(frozen=True, slots=True)
class FollowUpRequest:
    question: str
    answer_transcript: str
    reference_answer: str = ""
    prior_follow_ups: tuple[str, ...] = ()
    repair_errors: tuple[str, ...] = ()


class FollowUpOutcome(BaseModel):
    """The only shape a follow-up decision may take: both fields set, or both null."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    follow_up: str | None = Field(min_length=1, max_length=MAX_FOLLOW_UP_CHARS)
    reason: FollowUpReason | None


NO_FOLLOW_UP = FollowUpOutcome(follow_up=None, reason=None)


class FollowUpTransport(Protocol):
    async def follow_up(self, request: FollowUpRequest) -> Mapping[str, object]: ...


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z'-]*", text.casefold())


def _content_words(text: str) -> set[str]:
    return {word for word in _words(text) if len(word) >= 5 and word not in _COMMON_WORDS}


def _normalize(text: str) -> str:
    return " ".join(_words(text))


def pressure_probe_allowed(question: str, answer_transcript: str) -> bool:
    digest = hashlib.sha256(f"{question}:{answer_transcript}".encode()).digest()
    return digest[0] % PRESSURE_PROBE_ONE_IN == 0


def validate_follow_up(
    payload: Mapping[str, object],
    *,
    answer_transcript: str,
    prior_follow_ups: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Issues by name; empty means the decision may be used."""
    try:
        outcome = FollowUpOutcome.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "follow-up"
        return (f"follow-up {location}: {first['msg']}",)
    if (outcome.follow_up is None) != (outcome.reason is None):
        return ("follow_up and reason must both be set or both be null",)
    if outcome.follow_up is None:
        return ()
    text = outcome.follow_up.strip()
    if "\n" in text or text.count("?") != 1 or not text.endswith("?"):
        return ("the follow-up must be one spoken question ending in a question mark",)
    if len(_words(text)) > MAX_FOLLOW_UP_WORDS:
        return (f"the follow-up must be at most {MAX_FOLLOW_UP_WORDS} words",)
    if _normalize(text) in {_normalize(prior) for prior in prior_follow_ups}:
        return ("the follow-up repeats one that was already asked",)
    if not _content_words(text) & _content_words(answer_transcript):
        return ("the follow-up must reuse a word the learner actually said",)
    return ()


@dataclass
class _FollowUpRuntimeAdapter:
    transport: FollowUpTransport
    request: FollowUpRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        payload = await self.transport.follow_up(
            replace(self.request, repair_errors=repair_errors)
        )
        return TransportResult(payload=payload, turns=1)


class InterviewFollowUpService:
    def __init__(self, transport: FollowUpTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    async def decide(self, request: FollowUpRequest) -> FollowUpOutcome:
        """One bounded decision, or a contract error the caller renders as such."""
        if not request.question.strip():
            raise RoleContractError("the follow-up needs the question that was asked")
        if len(_words(request.answer_transcript)) < MINIMUM_ANSWER_WORDS:
            raise RoleContractError("the answer is too short to follow up on")
        if len(request.answer_transcript) > MAX_ANSWER_CHARS:
            raise RoleContractError("the answer is longer than the interviewer may read")
        if len(request.prior_follow_ups) >= MAX_FOLLOW_UPS:
            return NO_FOLLOW_UP
        if self._transport is None:
            raise InterviewFollowUpUnavailable(
                "the follow-up needs Claude enabled on the server"
            )
        runtime = BoundedClaudeRuntime(
            _FollowUpRuntimeAdapter(self._transport, request),
            validate=lambda payload: validate_follow_up(
                payload,
                answer_transcript=request.answer_transcript,
                prior_follow_ups=request.prior_follow_ups,
            ),
        )
        key = f"{request.question}:{request.answer_transcript}:{len(request.prior_follow_ups)}"
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"interview-follow-up:{digest}",
            job_type=INTERVIEW_FOLLOW_UP_JOB_TYPE,
            model=self._model,
            schema_id=INTERVIEW_FOLLOW_UP_SCHEMA_ID,
            prompt_version=INTERVIEW_FOLLOW_UP_PROMPT_VERSION,
            max_turns=INTERVIEW_FOLLOW_UP_MAX_TURNS,
            wall_time_seconds=INTERVIEW_FOLLOW_UP_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise InterviewFollowUpUnavailable(
                "the interviewer did not return a valid follow-up"
            ) from None
        except AgentRuntimeError as exc:
            raise InterviewFollowUpUnavailable(str(exc)) from None
        outcome = FollowUpOutcome.model_validate(result.payload)
        if outcome.reason == "pressure_probe" and not pressure_probe_allowed(
            request.question, request.answer_transcript
        ):
            return NO_FOLLOW_UP
        return outcome


def follow_up_schema() -> dict[str, object]:
    return FollowUpOutcome.model_json_schema()


def render_follow_up_prompt(request: FollowUpRequest) -> str:
    """The prompt the SDK transport sends: the question, the answer, what was already asked."""
    lines: list[str] = [
        "A learner preparing for Technical Account Manager interviews is practising aloud. "
        "You are the interviewer. This is practice, not a real interview.",
        f"Question asked: {request.question.strip()}",
    ]
    if request.prior_follow_ups:
        lines.append(
            "Follow-ups you already asked, in order (the answer below responds to the last "
            "one):\n" + "\n".join(f"- {prior.strip()}" for prior in request.prior_follow_ups)
        )
    lines.append(
        "The learner's answer, transcribed from the recording:\n"
        + request.answer_transcript.strip()
    )
    if request.reference_answer.strip():
        lines.append(
            "The learner's own reference answer (what they intended to say, not something "
            "they said):\n" + request.reference_answer.strip()
        )
    probe = (
        "If the answer is solid, you may still ask one pressure probe, the way a real "
        "interviewer tests a good answer; set reason to pressure_probe."
        if pressure_probe_allowed(request.question, request.answer_transcript)
        else "If the answer is solid, ask nothing: set follow_up and reason to null."
    )
    lines.append(
        "Decide whether to ask one follow-up. Ask one when something said is weak: a vague "
        "claim, a missing number, an assertion with no example; set reason to weak_point. "
        + probe
        + f" A follow-up is one short spoken question of at most {MAX_FOLLOW_UP_WORDS} words, "
        "ends in a question mark, reuses the learner's own words for the thing it targets, "
        "and never repeats an earlier follow-up. Never coach, hint at the answer, or comment "
        "on quality."
    )
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


__all__ = [
    "INTERVIEW_FOLLOW_UP_JOB_TYPE",
    "INTERVIEW_FOLLOW_UP_PROMPT_KEY",
    "INTERVIEW_FOLLOW_UP_PROMPT_VERSION",
    "INTERVIEW_FOLLOW_UP_SCHEMA_ID",
    "MAX_FOLLOW_UPS",
    "NO_FOLLOW_UP",
    "FollowUpOutcome",
    "FollowUpRequest",
    "FollowUpTransport",
    "InterviewFollowUpService",
    "InterviewFollowUpUnavailable",
    "follow_up_schema",
    "pressure_probe_allowed",
    "render_follow_up_prompt",
    "validate_follow_up",
]
```

- [ ] **Step 4: Run the role test and expect a pass.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/agents/test_interview_follow_up_service.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Write the failing transport test.** In `apps/backend/tests/unit/agents/test_sdk_runtime.py` add the import below the existing `from tamforge_backend.agents.compatibility import (...)` block:

```python
from tamforge_backend.agents.roles.interview_follow_up import FollowUpRequest
```

and append this test at the end of the file:

```python
@pytest.mark.anyio
async def test_follow_up_sends_the_answer_and_returns_the_decision() -> None:
    decision = {"follow_up": "What exactly was the ceiling you hit?", "reason": "weak_point"}
    query = FakeQuery(
        [SystemMessage(subtype="init", data={"model": "m"}), _result(structured_output=decision)]
    )
    request = FollowUpRequest(
        question="Why are you leaving?",
        answer_transcript="I hit the ceiling of what I can learn there.",
        prior_follow_ups=("Why now?",),
    )

    payload = await _runtime(query).follow_up(request)

    assert payload == decision
    prompt = query.calls[0]["prompt"]
    assert "Question asked: Why are you leaving?" in prompt and "- Why now?" in prompt
    assert query.calls[0]["options"].model == "claude-fable-5-1"
```

- [ ] **Step 6: Run it and watch it fail.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/agents/test_sdk_runtime.py -q -k follow_up`
Expected: FAIL with `AttributeError: 'AgentSdkRuntime' object has no attribute 'follow_up'`.

- [ ] **Step 7: Add the transport method.** In `apps/backend/src/tamforge_backend/agents/sdk_runtime.py`:

Add the import between `from .roles.debrief import DebriefRequest` and `from .roles.monthly_report import MonthlyReportRequest`:

```python
from .roles.interview_follow_up import FollowUpRequest
```

Add this constant directly after the `PRACTICE_REVIEW_SYSTEM_PROMPT = (...)` block:

```python
INTERVIEW_FOLLOW_UP_SYSTEM_PROMPT = (
    "You are the TAM Forge practice interviewer. The learner just answered one question "
    "aloud and the answer was transcribed. Decide whether a real interviewer would ask one "
    "short follow-up about something the learner actually said, or nothing. You never coach, "
    "never hint at the answer and never comment on quality. The learner's own reference "
    "answer is what they meant to say, never something they said. Answer in English. "
    "Return only the object."
)
```

Add this method directly after `review_practice`:

```python
    async def follow_up(self, request: FollowUpRequest) -> Mapping[str, object]:
        from .roles.interview_follow_up import follow_up_schema, render_follow_up_prompt

        run = await self._structured(
            prompt=render_follow_up_prompt(request),
            schema=follow_up_schema(),
            model=self._environ.get("TAMFORGE_REVIEWER_MODEL", "claude-fable-5-1"),
            system_prompt=INTERVIEW_FOLLOW_UP_SYSTEM_PROMPT,
            max_turns=4,
        )
        return {} if run.structured_output is None else dict(run.structured_output)
```

- [ ] **Step 8: Run both test files, ruff and mypy.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/agents/test_interview_follow_up_service.py apps/backend/tests/unit/agents/test_sdk_runtime.py -q`
Expected: all pass.
Run: `~/.local/bin/uv run ruff check apps/backend` then `~/.local/bin/uv run mypy apps/backend/src packages/protocol/src`
Expected: both clean.

- [ ] **Step 9: Commit.**

```bash
git add apps/backend/src/tamforge_backend/agents/roles/interview_follow_up.py apps/backend/src/tamforge_backend/agents/sdk_runtime.py apps/backend/tests/unit/agents/test_interview_follow_up_service.py apps/backend/tests/unit/agents/test_sdk_runtime.py
git commit -m "feat(agents): add the interview_follow_up role" -m "One bounded, tool-less decision per answer: a short spoken follow-up that reuses the learner's own words, or nothing. Pressure probes pass a deterministic one-in-three gate so they stay a minority." -m "Refs #390" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 2: Endpoint `POST /api/v1/practice-answers/follow-up`

**Files**
- Modify: `apps/backend/src/tamforge_backend/practice/schemas.py`
- Modify: `apps/backend/src/tamforge_backend/practice/routes.py`
- Modify: `apps/backend/src/tamforge_backend/main.py`
- Test (modify): `apps/backend/tests/unit/practice/test_practice_routes.py`

**Interfaces**
- Consumes (Task 1): `FollowUpRequest`, `FollowUpOutcome`, `InterviewFollowUpService.decide`, `InterviewFollowUpUnavailable`; existing `PracticeInvalid`, `PracticeUnavailable`, `practice_exception_handler`, `require_csrf_owner`, `Settings.claude_enabled`, `Settings.reviewer_model`.
- Produces:
  - `FollowUpCommand(question: str, reference_answer: str = "", transcript: str, prior_follow_ups: tuple[str, ...] = ())`
  - `FollowUpResponse(follow_up: str | None, reason: Literal["weak_point", "pressure_probe"] | None)`
  - `get_follow_up_service(request: Request) -> InterviewFollowUpService`
  - `app.state.interview_follow_up_transport`
  - route `POST /api/v1/practice-answers/follow-up` → 200 `FollowUpResponse`, 422 `practice_invalid`, 503 `practice_unavailable`

**Independent of:** Tasks 4, 5, 6.

`scripts/ci/tests/test_check_openapi.py` and `scripts/ci/check_openapi.py` go red from this task until Task 7 regenerates the contract; that is expected and Task 7 owns it.

- [ ] **Step 1: Write the failing route test.** In `apps/backend/tests/unit/practice/test_practice_routes.py` add these imports (keep the block sorted the way ruff wants it):

```python
from tamforge_backend.agents.roles.contracts import RoleContractError
from tamforge_backend.agents.roles.interview_follow_up import (
    FollowUpOutcome,
    FollowUpRequest,
    InterviewFollowUpUnavailable,
)
from tamforge_backend.practice.routes import get_follow_up_service, get_practice_service
```

(the last line replaces the existing `from tamforge_backend.practice.routes import get_practice_service`), and append:

```python
class StubFollowUps:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.requests: list[FollowUpRequest] = []

    async def decide(self, request: FollowUpRequest) -> FollowUpOutcome:
        if self.error is not None:
            raise self.error
        self.requests.append(request)
        return FollowUpOutcome(follow_up="What exactly was the ceiling?", reason="weak_point")


FOLLOW_UP_BODY = {
    "question": "Why are you leaving?",
    "reference_answer": "Four anchors.",
    "transcript": "I hit the ceiling of what I can learn there.",
    "prior_follow_ups": ["Why now?"],
}


def test_a_follow_up_is_decided_in_the_request_and_failures_stay_closed() -> None:
    client, _ = _client()
    follow_ups = StubFollowUps()
    overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_follow_up_service] = lambda: follow_ups
    path = "/api/v1/practice-answers/follow-up"
    with client:
        asked = client.post(path, json=FOLLOW_UP_BODY)
        bare = client.post(path, json={"question": "Why?", "transcript": "Because of scale."})
        three = client.post(path, json={**FOLLOW_UP_BODY, "prior_follow_ups": ["a?", "b?", "c?"]})
        unknown_field = client.post(path, json={**FOLLOW_UP_BODY, "recording_id": "x"})
        follow_ups.error = RoleContractError("internal")
        too_short = client.post(path, json=FOLLOW_UP_BODY)
        follow_ups.error = InterviewFollowUpUnavailable("internal")
        down = client.post(path, json=FOLLOW_UP_BODY)

    assert asked.status_code == 200
    assert asked.json() == {"follow_up": "What exactly was the ceiling?", "reason": "weak_point"}
    assert asked.headers["cache-control"] == "no-store"
    sent = follow_ups.requests[0]
    assert sent.question == "Why are you leaving?" and sent.prior_follow_ups == ("Why now?",)
    assert sent.answer_transcript == FOLLOW_UP_BODY["transcript"]
    assert sent.reference_answer == "Four anchors."
    assert bare.status_code == 200 and follow_ups.requests[1].prior_follow_ups == ()
    assert three.status_code == 422 and unknown_field.status_code == 422
    assert too_short.status_code == 422 and too_short.json()["code"] == "practice_invalid"
    assert down.status_code == 503 and down.json()["code"] == "practice_unavailable"
    assert "internal" not in too_short.text + down.text


def test_with_claude_disabled_the_follow_up_is_a_503_and_the_app_moves_on() -> None:
    client, _ = _client()
    with client:
        down = client.post("/api/v1/practice-answers/follow-up", json=FOLLOW_UP_BODY)
    assert down.status_code == 503 and down.json()["code"] == "practice_unavailable"
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/practice/test_practice_routes.py -q`
Expected: collection error, `ImportError: cannot import name 'get_follow_up_service'`.

- [ ] **Step 3: Add the wire shapes.** In `apps/backend/src/tamforge_backend/practice/schemas.py` add after `PracticeAnswerPage`:

```python
class FollowUpCommand(StrictModel):
    """The answer just given, transcribed on the Mac. The server never waits for its own
    transcription: the learner is in front of the app."""

    question: Annotated[str, Field(min_length=1, max_length=1000)]
    reference_answer: Annotated[str, Field(default="", max_length=65536)]
    transcript: Annotated[str, Field(min_length=1, max_length=40000)]
    prior_follow_ups: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=240)], ...],
        Field(default=(), max_length=2),
    ]


class FollowUpResponse(StrictModel):
    follow_up: str | None
    reason: Literal["weak_point", "pressure_probe"] | None
```

and add `"FollowUpCommand"` and `"FollowUpResponse"` at the top of `__all__`.

- [ ] **Step 4: Add the dependency and the route.** In `apps/backend/src/tamforge_backend/practice/routes.py`:

Replace the two import lines

```python
from ..agents.roles.practice_review import PracticeReviewService
```

and

```python
from .schemas import PracticeAnswerCommand, PracticeAnswerPage, PracticeAnswerResponse
```

with

```python
from ..agents.roles.contracts import RoleContractError
from ..agents.roles.interview_follow_up import (
    FollowUpRequest,
    InterviewFollowUpService,
    InterviewFollowUpUnavailable,
)
from ..agents.roles.practice_review import PracticeReviewService
```

and

```python
from .schemas import (
    FollowUpCommand,
    FollowUpResponse,
    PracticeAnswerCommand,
    PracticeAnswerPage,
    PracticeAnswerResponse,
)
```

Add after `get_practice_service`:

```python
def get_follow_up_service(request: Request) -> InterviewFollowUpService:
    settings = cast(Settings, request.app.state.settings)
    transport = getattr(request.app.state, "interview_follow_up_transport", None)
    if not settings.claude_enabled:
        transport = None
    return InterviewFollowUpService(transport, model=settings.reviewer_model)
```

Add after `submit_practice_answer`:

```python
@router.post("/follow-up", response_model=FollowUpResponse)
async def request_follow_up(
    command: FollowUpCommand,
    response: Response,
    service: Annotated[InterviewFollowUpService, Depends(get_follow_up_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> FollowUpResponse:
    """Decide, inside the request, whether the interviewer follows up on this answer.
    Nothing is stored. Any failure is a closed problem and the app moves on."""
    del owner
    try:
        outcome = await service.decide(
            FollowUpRequest(
                question=command.question,
                answer_transcript=command.transcript,
                reference_answer=command.reference_answer,
                prior_follow_ups=command.prior_follow_ups,
            )
        )
    except InterviewFollowUpUnavailable as exc:
        raise PracticeUnavailable(str(exc)) from None
    except RoleContractError as exc:
        raise PracticeInvalid(str(exc)) from None
    _prevent_storage(response)
    return FollowUpResponse(follow_up=outcome.follow_up, reason=outcome.reason)
```

Add `"get_follow_up_service"` to `__all__` before `"get_practice_service"`.

- [ ] **Step 5: Wire the transport.** In `apps/backend/src/tamforge_backend/main.py`, directly after the line `app.state.practice_review_transport = app.state.planner_transport`, add:

```python
            app.state.interview_follow_up_transport = app.state.planner_transport
```

- [ ] **Step 6: Run the tests, ruff and mypy.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/practice/test_practice_routes.py -q`
Expected: `4 passed`.
Run: `~/.local/bin/uv run ruff check apps/backend` then `~/.local/bin/uv run mypy apps/backend/src packages/protocol/src`
Expected: both clean.

- [ ] **Step 7: Commit.**

```bash
git add apps/backend/src/tamforge_backend/practice/schemas.py apps/backend/src/tamforge_backend/practice/routes.py apps/backend/src/tamforge_backend/main.py apps/backend/tests/unit/practice/test_practice_routes.py
git commit -m "feat(practice): decide a follow-up inside the request" -m "POST /api/v1/practice-answers/follow-up takes the Mac's transcript and answers with one follow-up or none. Claude disabled, a runtime failure or a refused output is a 503 problem; nothing is stored." -m "Refs #390" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 3: Follow-up columns and the `follow_up_handling` review dimension

**Files**
- Create: `apps/backend/alembic/versions/20260918_0035_follow_ups.py`
- Modify: `apps/backend/src/tamforge_backend/practice/models.py`
- Modify: `apps/backend/src/tamforge_backend/practice/schemas.py`
- Modify: `apps/backend/src/tamforge_backend/practice/service.py`
- Modify: `apps/backend/src/tamforge_backend/agents/roles/practice_review.py`
- Modify: `apps/backend/src/tamforge_backend/agents/sdk_runtime.py` (one sentence of `PRACTICE_REVIEW_SYSTEM_PROMPT`)
- Modify: `apps/backend/src/tamforge_backend/evals/practice_review.py`
- Modify: `apps/backend/src/tamforge_backend/evals/suite.py` (one description string)
- Modify: `apps/backend/tests/fixtures/evals/practice-review-refusal-cases.json`
- Test (modify): `apps/backend/tests/unit/agents/test_practice_review_service.py`
- Test (modify): `apps/backend/tests/unit/practice/test_practice_routes.py`
- Test (modify): `apps/backend/tests/evals/test_practice_review_refusals.py`
- Test (modify): `apps/backend/tests/integration/practice/test_practice_answers.py`
- Test (modify): `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py` (the Alembic head constant)

**Interfaces**
- Consumes: existing `PracticeAnswer`, `PracticeAnswerService`, `PracticeReviewRequest`, `validate_practice_review`, `render_practice_review_prompt`.
- Produces:
  - columns `practice_answers.follow_up_of BIGINT NULL` (FK to `practice_answers.id`, `ON DELETE CASCADE`) and `practice_answers.follow_up_question TEXT NULL`, paired by a check constraint
  - `PracticeAnswerCommand.follow_up_question: str | None`, `PracticeAnswerCommand.follow_up_of_recording_id: UUID | None` (both or neither)
  - `PracticeAnswerResponse.follow_up_of: int | None`, `PracticeAnswerResponse.follow_up_question: str | None`
  - `PracticeReviewRequest.follow_up_question: str = ""`, `.parent_question: str = ""`, `.parent_transcript: str = ""`, property `.is_follow_up`
  - `FOLLOW_UP_DIMENSION: tuple[str, str]`, `dimensions_for(*, follow_up: bool) -> tuple[tuple[str, str], ...]`
  - `validate_practice_review(payload, *, answer_transcript: str, follow_up: bool = False)`
  - `PRACTICE_REVIEW_PROMPT_VERSION = "v2"`, `PRACTICE_REVIEW_SCHEMA_ID = "urn:tamforge:schema:practice-review-v2"`

**Independent of:** Tasks 1, 4, 5, 6. It edits `practice/schemas.py` and `test_practice_routes.py`, which Task 2 also edits, so run it after Task 2 in the same worktree.

Design notes:
- `follow_up_of` points at the answer the follow-up was generated from (the immediately preceding answer in the chain), so a second follow-up links to the first follow-up's answer. The review's "earlier question" is that row's `follow_up_question` when it has one, else its `question`.
- `question` on a follow-up row stays the root question from the answer bank; `follow_up_question` is what the interviewer actually asked.
- The Mac knows recording ids, not server ids, so the command names the parent by `follow_up_of_recording_id`. A parent that has not reached the server yet is a 404 and the Mac's existing retry loop sends it again, parent first.
- A follow-up row's review queues only once both transcripts exist, because the review reads both.
- Stored v1 outcomes (three dimensions) still validate against `PracticeReviewOutcome` because only `max_length` moves, from 3 to 4.

- [ ] **Step 1: Write the failing review-role tests.** In `apps/backend/tests/unit/agents/test_practice_review_service.py` extend the import list with `FOLLOW_UP_DIMENSION`, `PRACTICE_REVIEW_PROMPT_VERSION`, `PRACTICE_REVIEW_SCHEMA_ID`, `PracticeReviewOutcome` and `dimensions_for`, and append:

```python
FOLLOW_UP_ANSWER = (
    "I changed the weekly meeting into a daily checkpoint and the customer renewed for two "
    "years after that"
)


def _follow_up_payload(*, handled: bool) -> dict[str, object]:
    dimensions: list[dict[str, str]] = [
        {
            "slug": "answer_clarity",
            "score": "3.0",
            "evidence": "I changed the weekly meeting",
            "note": "One change, stated first.",
        },
        {
            "slug": "technical_examples",
            "score": "2.5",
            "evidence": "a daily checkpoint",
            "note": "Concrete, no number.",
        },
        {
            "slug": "english_accuracy",
            "score": "3.5",
            "evidence": "the customer renewed for two years",
            "note": "Accurate simple past.",
        },
    ]
    if handled:
        dimensions.append(
            {
                "slug": "follow_up_handling",
                "score": "3.0",
                "evidence": "renewed for two years after that",
                "note": "Answers what was asked and adds the outcome.",
            }
        )
    return _payload(
        dimensions=dimensions,
        fixes=[
            {
                "heard": "after that",
                "say_instead": "within the quarter",
                "why": "A date makes the outcome checkable.",
            }
        ],
    )


def test_an_answer_to_a_follow_up_is_also_scored_on_how_it_was_handled() -> None:
    assert FOLLOW_UP_DIMENSION[0] == "follow_up_handling"
    assert dimensions_for(follow_up=False) == PRACTICE_DIMENSIONS
    assert dimensions_for(follow_up=True) == (*PRACTICE_DIMENSIONS, FOLLOW_UP_DIMENSION)
    assert PRACTICE_REVIEW_PROMPT_VERSION == "v2"
    assert PRACTICE_REVIEW_SCHEMA_ID == "urn:tamforge:schema:practice-review-v2"

    four = _follow_up_payload(handled=True)
    three = _follow_up_payload(handled=False)
    assert validate_practice_review(four, answer_transcript=FOLLOW_UP_ANSWER, follow_up=True) == ()
    missing = validate_practice_review(three, answer_transcript=FOLLOW_UP_ANSWER, follow_up=True)
    assert "follow_up_handling" in missing[0]
    # Without a follow-up the review is exactly what it was: three dimensions, no fourth.
    assert validate_practice_review(three, answer_transcript=FOLLOW_UP_ANSWER) == ()
    unexpected = validate_practice_review(four, answer_transcript=FOLLOW_UP_ANSWER)
    assert "exactly" in unexpected[0] and "follow_up_handling" not in unexpected[0]
    # A stored v1 outcome still loads.
    assert PracticeReviewOutcome.model_validate(_payload()).readiness == "drilling"


def test_the_follow_up_prompt_carries_the_earlier_exchange_as_context_only() -> None:
    request = _request(
        answer_transcript=FOLLOW_UP_ANSWER,
        follow_up_question="What exactly did you change?",
        parent_question="Tell me about a difficult customer.",
        parent_transcript="I had an unhappy customer and I improved things.",
    )
    assert request.is_follow_up and not _request().is_follow_up
    prompt = render_practice_review_prompt(request)
    assert "Earlier question: Tell me about a difficult customer." in prompt
    assert "context only, never quote it as evidence" in prompt
    assert "Follow-up the interviewer then asked: What exactly did you change?" in prompt
    assert "- follow_up_handling:" in prompt
    assert "- follow_up_handling:" not in render_practice_review_prompt(_request())


def test_the_service_holds_a_follow_up_review_to_four_dimensions() -> None:
    request = _request(
        answer_transcript=FOLLOW_UP_ANSWER,
        follow_up_question="What exactly did you change?",
        parent_question=QUESTION,
        parent_transcript=ANSWER,
    )
    transport = _Transport([_follow_up_payload(handled=False), _follow_up_payload(handled=True)])
    outcome = asyncio.run(PracticeReviewService(transport, model="m").review(request))
    assert [d.slug for d in outcome.dimensions][-1] == "follow_up_handling"
    assert "follow_up_handling" in transport.requests[1].repair_errors[0]
    assert transport.requests[1].parent_transcript == ANSWER
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/agents/test_practice_review_service.py -q`
Expected: collection error, `ImportError: cannot import name 'FOLLOW_UP_DIMENSION'`.

- [ ] **Step 3: Teach the review role the fourth dimension.** In `apps/backend/src/tamforge_backend/agents/roles/practice_review.py`:

Change `from dataclasses import dataclass, field` to `from dataclasses import dataclass, field, replace`.

Replace

```python
PRACTICE_REVIEW_SCHEMA_ID = "urn:tamforge:schema:practice-review-v1"
```

with `PRACTICE_REVIEW_SCHEMA_ID = "urn:tamforge:schema:practice-review-v2"`, and `PRACTICE_REVIEW_PROMPT_VERSION = "v1"` with `PRACTICE_REVIEW_PROMPT_VERSION = "v2"`.

Replace the comment and tuple

```python
# The interview tracker's dimensions a single uninterrupted answer can show. Follow-up
# handling is left out: a practice answer has no follow-up to handle.
PRACTICE_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("answer_clarity", "Answer clarity and structure"),
    ("technical_examples", "Technical examples and supporting evidence"),
    ("english_accuracy", "English accuracy visible in the transcript"),
)
```

with

```python
# The interview tracker's dimensions a single uninterrupted answer can show.
PRACTICE_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("answer_clarity", "Answer clarity and structure"),
    ("technical_examples", "Technical examples and supporting evidence"),
    ("english_accuracy", "English accuracy visible in the transcript"),
)
# Scored only when the answer responds to a follow-up the interviewer asked.
FOLLOW_UP_DIMENSION: tuple[str, str] = (
    "follow_up_handling",
    "Follow-up handling: answers what was asked and adds to the first answer",
)
```

Replace the `PracticeReviewRequest` dataclass with:

```python
@dataclass(frozen=True, slots=True)
class PracticeReviewRequest:
    question: str
    answer_transcript: str
    reference_answer: str = ""
    speech_metrics: Mapping[str, object] = field(default_factory=dict)
    # Set together when this answer responds to a follow-up: the follow-up that was asked,
    # and the question and transcript of the answer it followed.
    follow_up_question: str = ""
    parent_question: str = ""
    parent_transcript: str = ""
    repair_errors: tuple[str, ...] = ()

    @property
    def is_follow_up(self) -> bool:
        return bool(self.follow_up_question.strip())


def dimensions_for(*, follow_up: bool) -> tuple[tuple[str, str], ...]:
    return (*PRACTICE_DIMENSIONS, FOLLOW_UP_DIMENSION) if follow_up else PRACTICE_DIMENSIONS
```

In `PracticeReviewOutcome` change `dimensions: tuple[PracticeDimension, ...] = Field(min_length=1, max_length=3)` to `max_length=4`.

Change the validator signature and its expected list:

```python
def validate_practice_review(
    payload: Mapping[str, object], *, answer_transcript: str, follow_up: bool = False
) -> tuple[str, ...]:
```

```python
    expected = [slug for slug, _ in dimensions_for(follow_up=follow_up)]
```

In `_PracticeReviewRuntimeAdapter.invoke` replace the body after `del run` with:

```python
        payload = await self.transport.review_practice(
            replace(self.request, repair_errors=repair_errors)
        )
        return TransportResult(payload=payload, turns=1)
```

In `PracticeReviewService.review` replace the `validate=` lambda and the digest with:

```python
            validate=lambda payload: validate_practice_review(
                payload,
                answer_transcript=request.answer_transcript,
                follow_up=request.is_follow_up,
            ),
        )
        key = f"{request.question}:{request.follow_up_question}:{request.answer_transcript}"
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
```

In `render_practice_review_prompt` replace the opening list

```python
    lines: list[str] = [
        "A learner preparing for Technical Account Manager interviews practised one answer "
        "aloud, uninterrupted. This is practice, not a real interview.",
        f"Question asked: {request.question.strip()}",
        "The learner's answer, transcribed from the recording:\n"
        + request.answer_transcript.strip(),
    ]
```

with

```python
    lines: list[str] = [
        "A learner preparing for Technical Account Manager interviews practised one answer "
        "aloud, uninterrupted. This is practice, not a real interview.",
    ]
    if request.is_follow_up:
        lines.extend(
            [
                f"Earlier question: {request.parent_question.strip()}",
                "The learner's earlier answer (context only, never quote it as evidence):\n"
                + request.parent_transcript.strip(),
                f"Follow-up the interviewer then asked: {request.follow_up_question.strip()}",
                "The learner's answer to the follow-up, transcribed from the recording. "
                "This is the answer under review:\n" + request.answer_transcript.strip(),
            ]
        )
    else:
        lines.extend(
            [
                f"Question asked: {request.question.strip()}",
                "The learner's answer, transcribed from the recording:\n"
                + request.answer_transcript.strip(),
            ]
        )
```

and replace `+ "\n".join(f"- {slug}: {name}" for slug, name in PRACTICE_DIMENSIONS)` with

```python
        + "\n".join(
            f"- {slug}: {name}" for slug, name in dimensions_for(follow_up=request.is_follow_up)
        )
```

Add `"FOLLOW_UP_DIMENSION"` at the top of `__all__` and `"dimensions_for"` directly before `"practice_review_schema"`.

In `apps/backend/src/tamforge_backend/agents/sdk_runtime.py`, inside `PRACTICE_REVIEW_SYSTEM_PROMPT`, replace `"aloud and that was transcribed from its recording. Score the three dimensions you are "` with `"aloud and that was transcribed from its recording. Score the dimensions you are "`.

- [ ] **Step 4: Run the review-role tests and expect a pass.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/agents/test_practice_review_service.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Extend the practice-review eval.** In `apps/backend/tests/fixtures/evals/practice-review-refusal-cases.json` change `"fixture_version"` to `"practice-review-refusals-v2"` and append these two objects to `"cases"`:

```json
    {
      "case_id": "follow-up-handling-scored",
      "question": "Tell me about a difficult customer.",
      "follow_up_question": "What exactly did you change for that customer?",
      "parent_question": "Tell me about a difficult customer.",
      "parent_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things.",
      "answer_transcript": "I changed the weekly meeting into a daily checkpoint and the customer renewed for two years after that",
      "reference_answer": "",
      "answers": [
        {
          "dimensions": [
            {"slug": "answer_clarity", "score": "3.0", "evidence": "I changed the weekly meeting", "note": "One change, stated first."},
            {"slug": "technical_examples", "score": "2.5", "evidence": "a daily checkpoint", "note": "Concrete, no number."},
            {"slug": "english_accuracy", "score": "3.5", "evidence": "the customer renewed for two years", "note": "Accurate simple past."},
            {"slug": "follow_up_handling", "score": "3.0", "evidence": "renewed for two years after that", "note": "Answers what was asked and adds the outcome."}
          ],
          "strengths": ["Names the change in the first clause."],
          "fixes": [{"heard": "after that", "say_instead": "within the quarter", "why": "A date makes the outcome checkable."}],
          "reference_coverage": "",
          "readiness": "drilling"
        }
      ],
      "expect": "accepted"
    },
    {
      "case_id": "follow-up-handling-missing",
      "question": "Tell me about a difficult customer.",
      "follow_up_question": "What exactly did you change for that customer?",
      "parent_question": "Tell me about a difficult customer.",
      "parent_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things.",
      "answer_transcript": "I changed the weekly meeting into a daily checkpoint and the customer renewed for two years after that",
      "reference_answer": "",
      "answers": [
        {
          "dimensions": [
            {"slug": "answer_clarity", "score": "3.0", "evidence": "I changed the weekly meeting", "note": "One change, stated first."},
            {"slug": "technical_examples", "score": "2.5", "evidence": "a daily checkpoint", "note": "Concrete, no number."},
            {"slug": "english_accuracy", "score": "3.5", "evidence": "the customer renewed for two years", "note": "Accurate simple past."}
          ],
          "strengths": ["Names the change in the first clause."],
          "fixes": [{"heard": "after that", "say_instead": "within the quarter", "why": "A date makes the outcome checkable."}],
          "reference_coverage": "",
          "readiness": "drilling"
        }
      ],
      "expect": "refused_by_validator"
    }
```

In `apps/backend/tests/evals/test_practice_review_refusals.py` change the asserted version to `"practice-review-refusals-v2"` and add `"follow-up-handling-scored"` and `"follow-up-handling-missing"` to the `>=` set of case ids.

In `apps/backend/src/tamforge_backend/evals/practice_review.py`:
- set `PRACTICE_REVIEW_EVALUATOR_VERSION: Final = "practice-review-refusals-v2"`
- add three fields to `PracticeReviewCase` after `reference_answer: str`:

```python
    follow_up_question: str
    parent_question: str
    parent_transcript: str
```

- in `load_practice_review_cases` add after `reference_answer=...`:

```python
                follow_up_question=str(raw.get("follow_up_question", "")),
                parent_question=str(raw.get("parent_question", "")),
                parent_transcript=str(raw.get("parent_transcript", "")),
```

- in `run_practice_review_case` add to the `PracticeReviewRequest(...)` call, after `reference_answer=case.reference_answer,`:

```python
        follow_up_question=case.follow_up_question,
        parent_question=case.parent_question,
        parent_transcript=case.parent_transcript,
```

In `apps/backend/src/tamforge_backend/evals/suite.py` replace `f"{len(practice.outcomes)} cases against {practice.model}: three dimensions once, "` with `f"{len(practice.outcomes)} cases against {practice.model}: each dimension once, "`.

Run: `~/.local/bin/uv run pytest apps/backend/tests/evals/test_practice_review_refusals.py apps/backend/tests/evals/test_suite.py -q`
Expected: all pass (the existing `follow-up-dimension-scored` case still ends `refused_by_validator`: it has no follow-up).

- [ ] **Step 6: Write the failing wire-shape tests.** In `apps/backend/tests/unit/practice/test_practice_routes.py`, inside `_answer(...)`, add two arguments to the `PracticeAnswerResponse(...)` call after `reference_material_id=2,`:

```python
        follow_up_of=None,
        follow_up_question=None,
```

and append:

```python
def test_a_follow_up_answer_names_its_question_and_its_parent_or_neither() -> None:
    client, service = _client()
    parent = "7a1f6e0c-3d52-4b8e-9c11-2f4a5b6c7d8e"
    body = {"question": "Why are you leaving?", "recording_id": str(RECORDING)}
    linked = {**body, "follow_up_question": "What was the ceiling?"}
    with client:
        both = client.post(
            "/api/v1/practice-answers", json={**linked, "follow_up_of_recording_id": parent}
        )
        only_question = client.post("/api/v1/practice-answers", json=linked)
        only_parent = client.post(
            "/api/v1/practice-answers", json={**body, "follow_up_of_recording_id": parent}
        )
        listed = client.get("/api/v1/practice-answers")

    assert both.status_code == 202
    assert service.submitted[0].follow_up_question == "What was the ceiling?"
    assert str(service.submitted[0].follow_up_of_recording_id) == parent
    assert only_question.status_code == 422 and only_parent.status_code == 422
    item = listed.json()["items"][0]
    assert item["follow_up_of"] is None and item["follow_up_question"] is None
```

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/practice/test_practice_routes.py -q`
Expected: FAIL, `pydantic ... Extra inputs are not permitted` for `follow_up_of` in `_answer`.

- [ ] **Step 7: Add the wire fields.** In `apps/backend/src/tamforge_backend/practice/schemas.py`:

Change `from pydantic import BaseModel, ConfigDict, Field` to `from pydantic import BaseModel, ConfigDict, Field, model_validator`.

Replace `PracticeAnswerCommand` with:

```python
class PracticeAnswerCommand(StrictModel):
    """One recorded practice answer. Sending it again for the same recording is a retry:
    it changes nothing stored and queues the review once the transcript exists.

    An answer to a follow-up names the follow-up that was asked and the recording of the
    answer it followed; both or neither."""

    question: Annotated[str, Field(min_length=1, max_length=1000)]
    recording_id: UUID
    reference_material_id: Annotated[int | None, Field(default=None, ge=1)]
    follow_up_question: Annotated[str | None, Field(default=None, min_length=1, max_length=1000)]
    follow_up_of_recording_id: Annotated[UUID | None, Field(default=None)]

    @model_validator(mode="after")
    def _follow_up_is_paired(self) -> PracticeAnswerCommand:
        asked = bool((self.follow_up_question or "").strip())
        if asked != (self.follow_up_of_recording_id is not None):
            raise ValueError("a follow-up answer needs its question and its parent recording")
        return self
```

In `PracticeAnswerResponse` add after `reference_material_id: int | None`:

```python
    follow_up_of: int | None
    follow_up_question: str | None
```

- [ ] **Step 8: Add the columns to the model.** In `apps/backend/src/tamforge_backend/practice/models.py`, inside `__table_args__`, add after the `fk_practice_answers_reference` constraint:

```python
        ForeignKeyConstraint(
            ["follow_up_of"],
            ["practice_answers.id"],
            name="fk_practice_answers_follow_up_of",
            ondelete="CASCADE",
        ),
```

and after the `reference_bounded` check:

```python
        CheckConstraint(
            "(follow_up_of IS NULL) = (follow_up_question IS NULL)", name="follow_up_paired"
        ),
        CheckConstraint(
            "follow_up_question IS NULL OR (btrim(follow_up_question) <> '' "
            "AND octet_length(follow_up_question) <= 2048)",
            name="follow_up_question_bounded",
        ),
```

and the two mapped columns after `reference_answer`:

```python
    # Set together when this answer responds to a follow-up: the answer it followed, and
    # what the interviewer asked. `question` stays the answer-bank question.
    follow_up_of: Mapped[int | None] = mapped_column(BigInteger)
    follow_up_question: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 9: Write the migration.** Create `apps/backend/alembic/versions/20260918_0035_follow_ups.py`:

```python
"""A practice answer may respond to a follow-up on an earlier practice answer."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_0035_follow_ups"
down_revision = "20260918_0034_practice_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("practice_answers", sa.Column("follow_up_of", sa.BigInteger(), nullable=True))
    op.add_column("practice_answers", sa.Column("follow_up_question", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_practice_answers_follow_up_of",
        "practice_answers",
        "practice_answers",
        ["follow_up_of"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "follow_up_paired",
        "practice_answers",
        "(follow_up_of IS NULL) = (follow_up_question IS NULL)",
    )
    op.create_check_constraint(
        "follow_up_question_bounded",
        "practice_answers",
        "follow_up_question IS NULL OR (btrim(follow_up_question) <> '' "
        "AND octet_length(follow_up_question) <= 2048)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_practice_answers_follow_up_question_bounded"), "practice_answers", type_="check"
    )
    op.drop_constraint(
        op.f("ck_practice_answers_follow_up_paired"), "practice_answers", type_="check"
    )
    op.drop_constraint(
        "fk_practice_answers_follow_up_of", "practice_answers", type_="foreignkey"
    )
    op.drop_column("practice_answers", "follow_up_question")
    op.drop_column("practice_answers", "follow_up_of")
```

In `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py`, in `test_alembic_has_exactly_one_linear_head`, change the asserted head to `"20260918_0035_follow_ups (head)"`.

- [ ] **Step 10: Store, gate and review the link in the service.** In `apps/backend/src/tamforge_backend/practice/service.py`:

Change `_DIMENSION_NAMES = dict(PRACTICE_DIMENSIONS)` to `_DIMENSION_NAMES = dict((*PRACTICE_DIMENSIONS, FOLLOW_UP_DIMENSION))` and add `FOLLOW_UP_DIMENSION,` as the first name in the `from ..agents.roles.practice_review import (...)` block.

In `submit`, inside `if row is None:`, directly before `row = PracticeAnswer(`, add:

```python
                    parent_id: int | None = None
                    if command.follow_up_of_recording_id is not None:
                        parent_id = await self._session.scalar(
                            select(PracticeAnswer.id)
                            .join(
                                Recording,
                                (Recording.owner_id == PracticeAnswer.owner_id)
                                & (Recording.id == PracticeAnswer.recording_id),
                            )
                            .where(PracticeAnswer.owner_id == owner_id)
                            .where(
                                Recording.client_recording_id
                                == command.follow_up_of_recording_id
                            )
                        )
                        if parent_id is None:
                            raise PracticeNotFound(
                                "the parent answer has not reached the server yet"
                            )
```

and add two arguments to the `PracticeAnswer(...)` call after `reference_answer=reference,`:

```python
                        follow_up_of=parent_id,
                        follow_up_question=(command.follow_up_question or "").strip() or None,
```

Still in `submit`, directly after the line `answer = "" if reviewed else await self._answer_text(owner_id, recording_pk)`, add:

```python
                if answer and row.follow_up_of is not None:
                    # The review reads the earlier answer too, so it waits for that transcript.
                    parent = await self._session.get(PracticeAnswer, row.follow_up_of)
                    parent_text = (
                        await self._answer_text(owner_id, parent.recording_id) if parent else ""
                    )
                    if not parent_text:
                        answer = ""
```

In `process`, directly after the `metrics = await self._session.scalar(...)` statement, add:

```python
                follow_up_question = parent_question = parent_transcript = ""
                if row.follow_up_of is not None:
                    parent = await self._session.get(PracticeAnswer, row.follow_up_of)
                    if parent is None or parent.owner_id != owner_id:
                        raise PracticeInvalid("the parent answer was not found")
                    follow_up_question = row.follow_up_question or ""
                    parent_question = parent.follow_up_question or parent.question
                    parent_transcript = await self._answer_text(owner_id, parent.recording_id)
```

and add three arguments to the `PracticeReviewRequest(...)` call after `speech_metrics=dict(metrics or {}),`:

```python
                            follow_up_question=follow_up_question,
                            parent_question=parent_question,
                            parent_transcript=parent_transcript,
```

In `_response`, add after `reference_material_id=row.reference_material_id,`:

```python
        follow_up_of=row.follow_up_of,
        follow_up_question=row.follow_up_question,
```

- [ ] **Step 11: Run the unit tests and expect a pass.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/unit/practice apps/backend/tests/unit/agents/test_practice_review_service.py apps/backend/tests/unit/roadmaps/test_curriculum_schema.py apps/backend/tests/unit/workers/test_claude_practice_review_step.py -q`
Expected: all pass.

- [ ] **Step 12: Write the integration test.** Append to `apps/backend/tests/integration/practice/test_practice_answers.py`:

```python
FOLLOW_UP_ANSWER = (
    "I changed the weekly meeting into a daily checkpoint and the customer renewed for two years"
)


class FollowUpAwareTransport(FakePracticeTransport):
    async def review_practice(self, request: object) -> Mapping[str, object]:
        payload = dict(await super().review_practice(request))
        if getattr(request, "is_follow_up", False):
            payload["dimensions"] = [
                {
                    "slug": "answer_clarity",
                    "score": "3.0",
                    "evidence": "I changed the weekly meeting",
                    "note": "One change, stated first.",
                },
                {
                    "slug": "technical_examples",
                    "score": "2.5",
                    "evidence": "a daily checkpoint",
                    "note": "Concrete, no number.",
                },
                {
                    "slug": "english_accuracy",
                    "score": "3.5",
                    "evidence": "the customer renewed",
                    "note": "Accurate simple past.",
                },
                {
                    "slug": "follow_up_handling",
                    "score": "3.0",
                    "evidence": "renewed for two years",
                    "note": "Answers what was asked.",
                },
            ]
            payload["fixes"] = [
                {
                    "heard": "a daily checkpoint",
                    "say_instead": "a fifteen minute daily checkpoint",
                    "why": "A number makes it concrete.",
                }
            ]
        return payload


def test_a_follow_up_answer_is_linked_and_scored_on_handling(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.practice_review import PracticeReviewService
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.practice.models import PracticeAnswer
    from tamforge_backend.practice.schemas import PracticeAnswerCommand
    from tamforge_backend.practice.service import PracticeAnswerService, PracticeNotFound
    from tamforge_backend.recordings.models import Recording
    from tamforge_backend.speech.analysis import SpeechAnalysisService
    from tamforge_backend.speech.repository import SqlAlchemyTranscriptRepository
    from tamforge_backend.speech.service import TranscriptService
    from tamforge_backend.testing.speech import insert_stored_recording, transcript_command
    from tamforge_backend.workers.claude import practice_review_step

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()
            first_recording = insert_stored_recording(
                connection, owner_id=owner_id, started_at=datetime(2026, 9, 17, 17, tzinfo=UTC)
            )
            second_recording = insert_stored_recording(
                connection, owner_id=owner_id, started_at=datetime(2026, 9, 17, 17, 2, tzinfo=UTC)
            )

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            transport = FollowUpAwareTransport()
            reviewer = PracticeReviewService(transport, model="claude-fable-5-1")
            now = datetime(2026, 9, 17, 17, 5, tzinfo=UTC)
            first = PracticeAnswerCommand(
                question="Tell me about a difficult customer.", recording_id=first_recording
            )
            second = PracticeAnswerCommand(
                question="Tell me about a difficult customer.",
                recording_id=second_recording,
                follow_up_question="What exactly did you change?",
                follow_up_of_recording_id=first_recording,
            )

            async def transcribe(recording_id: object, said: str) -> None:
                async with factory() as session:
                    transcripts = TranscriptService(
                        session, SqlAlchemyTranscriptRepository(session)
                    )
                    await transcripts.submit(
                        owner_id=owner_id,
                        recording_id=recording_id,  # type: ignore[arg-type]
                        command=transcript_command(
                            track="microphone", segments=[(2000, 9000, said)]
                        ),
                    )
                    recording_pk = await session.scalar(
                        select(Recording.id).where(Recording.client_recording_id == recording_id)
                    )
                    await session.rollback()
                    assert recording_pk is not None
                    await SpeechAnalysisService(session).process(
                        owner_id=owner_id, recording_pk=recording_pk
                    )

            try:
                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    # The follow-up cannot arrive before the answer it followed.
                    with pytest.raises(PracticeNotFound):
                        await service.submit(owner_id=owner_id, command=second)
                    parent = await service.submit(owner_id=owner_id, command=first)
                    child = await service.submit(owner_id=owner_id, command=second)
                    assert child.follow_up_of == parent.id
                    assert child.follow_up_question == "What exactly did you change?"
                    assert parent.follow_up_of is None and parent.follow_up_question is None

                # Only the follow-up is transcribed: its review waits for the earlier answer.
                await transcribe(second_recording, FOLLOW_UP_ANSWER)
                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    waiting = await service.submit(owner_id=owner_id, command=second)
                    assert waiting.status == "awaiting_transcript"

                await transcribe(first_recording, ANSWER)
                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    for wanted in (first, second):
                        queued = await service.submit(owner_id=owner_id, command=wanted)
                        assert queued.status == "queued"
                assert await practice_review_step(factory, reviewer=reviewer) == 1
                assert await practice_review_step(factory, reviewer=reviewer) == 1

                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    page = await service.list(owner_id=owner_id)
                    by_id = {item.id: item for item in page.items}
                    assert [d.slug for d in by_id[parent.id].dimensions] == [
                        "answer_clarity",
                        "technical_examples",
                        "english_accuracy",
                    ]
                    handled = by_id[child.id].dimensions[-1]
                    assert handled.slug == "follow_up_handling"
                    assert handled.name.startswith("Follow-up handling")
                    versions = (
                        await session.scalars(select(PracticeAnswer.prompt_version))
                    ).all()
                    await session.rollback()
                    assert set(versions) == {"v2"}

                linked = [r for r in transport.requests if getattr(r, "is_follow_up", False)]
                assert len(linked) == 1
                assert linked[0].answer_transcript == FOLLOW_UP_ANSWER  # type: ignore[attr-defined]
                assert linked[0].parent_transcript == ANSWER  # type: ignore[attr-defined]
                assert linked[0].parent_question == first.question  # type: ignore[attr-defined]
                asked = linked[0].follow_up_question  # type: ignore[attr-defined]
                assert asked == second.follow_up_question
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()
```

- [ ] **Step 13: Run the integration tests against your own database.**

Bring up a private container if this checkout has none (`docker run -d --name tamforge-postgres-54331 -e POSTGRES_DB=tamforge -e POSTGRES_USER=tamforge -e POSTGRES_PASSWORD=tamforge -p 127.0.0.1:54331:5432 pgvector/pgvector:pg16`, then `docker exec tamforge-postgres-54331 createdb -U tamforge tamforge_test`).

Run: `TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54331/tamforge_test ~/.local/bin/uv run pytest -m "integration and not postgres_integration" apps/backend/tests/integration/practice -q`
Expected: `2 passed`. This is also the only local check of the migration's revision id length and of `downgrade`.

- [ ] **Step 14: Run the issue's verification command, ruff and mypy.**

Run: `~/.local/bin/uv run pytest apps/backend/tests -q -k practice`
Expected: all selected tests pass (integration tests are deselected by the default marker filter).
Run: `~/.local/bin/uv run ruff check .` then `~/.local/bin/uv run mypy apps/backend/src packages/protocol/src`
Expected: both clean.

- [ ] **Step 15: Commit.**

```bash
git add apps/backend/alembic/versions/20260918_0035_follow_ups.py apps/backend/src/tamforge_backend/practice apps/backend/src/tamforge_backend/agents/roles/practice_review.py apps/backend/src/tamforge_backend/agents/sdk_runtime.py apps/backend/src/tamforge_backend/evals/practice_review.py apps/backend/src/tamforge_backend/evals/suite.py apps/backend/tests/fixtures/evals/practice-review-refusal-cases.json apps/backend/tests/unit/agents/test_practice_review_service.py apps/backend/tests/unit/practice/test_practice_routes.py apps/backend/tests/evals/test_practice_review_refusals.py apps/backend/tests/integration/practice/test_practice_answers.py apps/backend/tests/unit/roadmaps/test_curriculum_schema.py
git commit -m "feat(practice): grade how a follow-up was handled" -m "A practice answer may now link to the answer it followed and carry the follow-up that was asked. Its review reads the earlier exchange as context and scores a fourth dimension, follow_up_handling; answers without a follow-up review exactly as before. Prompt v2, schema practice-review-v2; stored v1 outcomes still load." -m "Refs #390" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 4: Eval for the follow-up role

**Files**
- Create: `apps/backend/src/tamforge_backend/evals/interview_follow_up.py`
- Create: `apps/backend/tests/fixtures/evals/interview-follow-up-cases.json`
- Modify: `apps/backend/src/tamforge_backend/evals/suite.py`
- Test (create): `apps/backend/tests/evals/test_interview_follow_up.py`
- Test (modify): `apps/backend/tests/evals/test_suite.py`

**Interfaces**
- Consumes (Task 1): `FollowUpRequest`, `InterviewFollowUpService`, `InterviewFollowUpUnavailable`; `RoleContractError`.
- Produces: `INTERVIEW_FOLLOW_UP_EVALUATOR_VERSION = "interview-follow-up-v1"`, `PRESSURE_PROBE_MAX_SHARE = 0.5`, `FollowUpReport(model, fixture_version, outcomes)` with `.held`, `.pressure_probe_share`, `.passed`; `load_follow_up_cases(path)`, `run_follow_up_cases(path)`; suite part `"interview_follow_up"`.

**Independent of:** Tasks 2, 3, 5, 6. (Task 3 also edits `evals/suite.py`, one unrelated string; if both run in parallel worktrees the merge is trivial.)

The eval is scripted like every other role eval in this repo (CI has no model). Its two claims:
- *Follow-ups target something actually said:* an invented target and a target that exists only in the reference answer are both refused by the validator, and every accepted follow-up passed the same check.
- *Pressure probes appear on a minority of good answers:* all nine `good` cases script a pressure probe, so the share that ends in a follow-up is exactly the share the role's gate lets through. It must be above zero and below one half. With this fixture it is 1 of 9.

- [ ] **Step 1: Write the fixture.** Create `apps/backend/tests/fixtures/evals/interview-follow-up-cases.json`:

```json
{
  "fixture_version": "interview-follow-up-v1",
  "model": "claude-fable-5-1",
  "cases": [
    {"case_id": "answer-too-short", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "It went fine.", "answers": [{"follow_up": null, "reason": null}], "expect": "refused_by_contract"},
    {"case_id": "no-question", "kind": "refusal", "question": "   ", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "answers": [{"follow_up": null, "reason": null}], "expect": "refused_by_contract"},
    {"case_id": "limit-already-reached", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "prior_follow_ups": ["What exactly did you change for that unhappy customer?", "How did you know it went better?"], "answers": [{"follow_up": "Who on the team did the work?", "reason": "weak_point"}], "expect": "none_without_model"},
    {"case_id": "weak-point-targets-what-was-said", "kind": "weak", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "reference_answer": "Escalation, daily checkpoint, webhook retry fix in two days, two year renewal.", "answers": [{"follow_up": "What exactly did you change for that unhappy customer?", "reason": "weak_point"}], "expect": "follow_up"},
    {"case_id": "second-follow-up-after-one", "kind": "weak", "question": "Tell me about a difficult customer.", "answer_transcript": "I changed the weekly meeting and the customer was happier after some time with the new process we had.", "prior_follow_ups": ["What exactly did you change for that unhappy customer?"], "answers": [{"follow_up": "How do you know the customer was happier?", "reason": "weak_point"}], "expect": "follow_up"},
    {"case_id": "invented-target", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "answers": [{"follow_up": "How large was the Kubernetes migration budget?", "reason": "weak_point"}], "expect": "refused_by_validator"},
    {"case_id": "target-only-in-the-reference-answer", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "reference_answer": "Escalation, daily checkpoint, webhook retry fix in two days, two year renewal.", "answers": [{"follow_up": "How did the webhook retry fail?", "reason": "weak_point"}], "expect": "refused_by_validator"},
    {"case_id": "two-questions-at-once", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "answers": [{"follow_up": "What did the customer say? Who was on the team?", "reason": "weak_point"}], "expect": "refused_by_validator"},
    {"case_id": "longer-than-thirty-words", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "answers": [{"follow_up": "When you say the customer was unhappy and that you worked hard with the team to improve things and that it went much better for everyone in the end, what exactly did you do first?", "reason": "weak_point"}], "expect": "refused_by_validator"},
    {"case_id": "repeats-an-earlier-follow-up", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "prior_follow_ups": ["What exactly did you change for that unhappy customer?"], "answers": [{"follow_up": "What exactly did you change for that unhappy customer?", "reason": "weak_point"}], "expect": "refused_by_validator"},
    {"case_id": "reason-without-a-question", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "answers": [{"follow_up": null, "reason": "weak_point"}], "expect": "refused_by_validator"},
    {"case_id": "unknown-reason", "kind": "refusal", "question": "Tell me about a difficult customer.", "answer_transcript": "I had a customer who was very unhappy and I worked hard with the team to improve things and in the end it went much better for everyone.", "answers": [{"follow_up": "What exactly did you change for that unhappy customer?", "reason": "curiosity"}], "expect": "refused_by_validator"},
    {"case_id": "solid-answer-no-follow-up", "kind": "refusal", "question": "How do you prioritise competing requests?", "answer_transcript": "I rank requests by revenue at risk and effort. Last quarter I had five open asks, I shipped the two that protected ninety thousand dollars in renewals and told the other three customers a date.", "answers": [{"follow_up": null, "reason": null}], "expect": "none"},
    {"case_id": "good-webhook", "kind": "good", "question": "Tell me about a difficult customer.", "answer_transcript": "One customer escalated three times in a week about sync latency. I set up a daily checkpoint, traced it to a misconfigured webhook retry, fixed it in two days, and they renewed for two years.", "answers": [{"follow_up": "What would you have done if the webhook fix had not worked?", "reason": "pressure_probe"}], "expect": "follow_up"},
    {"case_id": "good-renewals", "kind": "good", "question": "How do you prioritise competing requests?", "answer_transcript": "I rank requests by revenue at risk and effort. Last quarter I had five open asks, I shipped the two that protected ninety thousand dollars in renewals and told the other three customers a date.", "answers": [{"follow_up": "How did you decide which renewals mattered most?", "reason": "pressure_probe"}], "expect": "none"},
    {"case_id": "good-exports", "kind": "good", "question": "Describe a time you explained something technical.", "answer_transcript": "A finance lead did not understand why exports were slow. I drew the pipeline as three boxes, showed the forty second database scan, and we agreed on a nightly export that cut it to four seconds.", "answers": [{"follow_up": "What if the finance lead had refused the nightly export?", "reason": "pressure_probe"}], "expect": "none"},
    {"case_id": "good-playbook", "kind": "good", "question": "Why do you want this role?", "answer_transcript": "I have run onboarding for twenty five customers alone. I want to do the same work with a team, on accounts with thousands of seats, where the playbook I wrote gets tested by other people.", "answers": [{"follow_up": "What happens when the team rejects your playbook?", "reason": "pressure_probe"}], "expect": "none"},
    {"case_id": "good-checklist", "kind": "good", "question": "Tell me about a mistake you made.", "answer_transcript": "I pushed a schema change on a Friday without telling support. Two customers saw errors for an hour. I rolled it back in ten minutes, wrote the incident note, and added a release checklist we still use.", "answers": [{"follow_up": "Why was there no release checklist before that Friday?", "reason": "pressure_probe"}], "expect": "none"},
    {"case_id": "good-cancellation", "kind": "good", "question": "How do you handle an angry customer on a call?", "answer_transcript": "I let them finish, repeat the problem in one sentence, and give a time for the next update. With a logistics customer last March that turned a cancellation threat into a thirty day action plan.", "answers": [{"follow_up": "What if the logistics customer had cancelled anyway?", "reason": "pressure_probe"}], "expect": "none"},
    {"case_id": "good-retention", "kind": "good", "question": "How do you measure your own success?", "answer_transcript": "Net revenue retention and time to first value. My accounts renewed at one hundred and eight percent last year and new customers reached their first dashboard in nine days instead of twenty one.", "answers": [{"follow_up": "How much of that retention was really your work?", "reason": "pressure_probe"}], "expect": "none"},
    {"case_id": "good-invoices", "kind": "good", "question": "Tell me about working with engineering.", "answer_transcript": "I file bugs with a reproduction, the customer impact in dollars, and a deadline. Engineering fixed a billing rounding bug in three days because the ticket showed eleven invoices were wrong.", "answers": [{"follow_up": "What do you do when engineering ignores the deadline?", "reason": "pressure_probe"}], "expect": "none"},
    {"case_id": "good-ninety-days", "kind": "good", "question": "What would you do in your first ninety days?", "answer_transcript": "Thirty days listening to the top ten accounts, thirty days fixing the two most repeated complaints, and thirty days writing the playbook so the next hire ramps in half the time.", "answers": [{"follow_up": "What if the top accounts disagree about the complaints?", "reason": "pressure_probe"}], "expect": "none"}
  ]
}
```

The `expect` of every `good` case follows from `pressure_probe_allowed(question, answer_transcript)`; changing a single character of a question or a transcript can flip it. Do not edit those strings.

- [ ] **Step 2: Write the failing eval test.** Create `apps/backend/tests/evals/test_interview_follow_up.py`:

```python
"""Follow-ups target what was said, and pressure probes stay a minority of good answers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.interview_follow_up import (
    PRESSURE_PROBE_MAX_SHARE,
    FollowUpReport,
    load_follow_up_cases,
    run_follow_up_cases,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "interview-follow-up-cases.json"
)


@pytest.fixture(scope="module")
def report() -> FollowUpReport:
    return asyncio.run(run_follow_up_cases(FIXTURE))


def test_the_fixture_pins_the_model_and_covers_every_ending() -> None:
    model, version, cases = load_follow_up_cases(FIXTURE)
    assert model == "claude-fable-5-1" and version == "interview-follow-up-v1"
    assert {case.expect for case in cases} == {
        "refused_by_contract",
        "refused_by_validator",
        "none",
        "none_without_model",
        "follow_up",
    }
    assert {case.case_id for case in cases} >= {
        "invented-target",
        "target-only-in-the-reference-answer",
        "weak-point-targets-what-was-said",
        "limit-already-reached",
    }
    assert sum(case.kind == "good" for case in cases) >= 8


def test_every_case_ends_the_way_the_fixture_says(report: FollowUpReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed


def test_follow_ups_target_something_actually_said(report: FollowUpReport) -> None:
    by_id = {o.case_id: o for o in report.outcomes}
    assert by_id["invented-target"].observed == "refused_by_validator"
    assert by_id["target-only-in-the-reference-answer"].observed == "refused_by_validator"
    assert by_id["weak-point-targets-what-was-said"].observed == "follow_up"


def test_pressure_probes_land_on_a_minority_of_good_answers(report: FollowUpReport) -> None:
    assert 0.0 < report.pressure_probe_share < PRESSURE_PROBE_MAX_SHARE


def test_a_contract_refusal_and_a_spent_budget_never_reach_the_model(
    report: FollowUpReport,
) -> None:
    silent = [
        o for o in report.outcomes if o.expected in {"refused_by_contract", "none_without_model"}
    ]
    assert silent and all(not o.model_called for o in silent)
```

Run: `~/.local/bin/uv run pytest apps/backend/tests/evals/test_interview_follow_up.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tamforge_backend.evals.interview_follow_up'`.

- [ ] **Step 3: Write the eval.** Create `apps/backend/src/tamforge_backend/evals/interview_follow_up.py`:

```python
"""Interview follow-ups: they target something said, and probes stay a minority.

Each case hands the interviewer a question, a transcribed answer and a scripted reply, and
states how the run must end: refused by the role contract before any model is called,
refused by the output validator, no follow-up, or one follow-up. The good-answer cases all
script a pressure probe, so the share of them that ends in a follow-up is the share of
solid answers the role lets a probe through on; it must be above zero and below half.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.interview_follow_up import (
    FollowUpRequest,
    InterviewFollowUpService,
    InterviewFollowUpUnavailable,
)

INTERVIEW_FOLLOW_UP_EVALUATOR_VERSION: Final = "interview-follow-up-v1"
PRESSURE_PROBE_MAX_SHARE: Final = 0.5
Outcome = Literal[
    "refused_by_contract", "refused_by_validator", "none", "none_without_model", "follow_up"
]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "none", "none_without_model", "follow_up"}
)
KINDS: Final[frozenset[str]] = frozenset({"weak", "good", "refusal"})


@dataclass(frozen=True, slots=True)
class FollowUpCase:
    case_id: str
    kind: Literal["weak", "good", "refusal"]
    question: str
    answer_transcript: str
    reference_answer: str
    prior_follow_ups: tuple[str, ...]
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class FollowUpCaseOutcome:
    case_id: str
    kind: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class FollowUpReport:
    model: str
    fixture_version: str
    outcomes: tuple[FollowUpCaseOutcome, ...]

    @property
    def held(self) -> int:
        return sum(outcome.held for outcome in self.outcomes)

    @property
    def pressure_probe_share(self) -> float:
        good = [o for o in self.outcomes if o.kind == "good"]
        return sum(o.observed == "follow_up" for o in good) / len(good) if good else 0.0

    @property
    def passed(self) -> bool:
        return (
            bool(self.outcomes)
            and self.held == len(self.outcomes)
            and 0.0 < self.pressure_probe_share < PRESSURE_PROBE_MAX_SHARE
        )


class _ScriptedTransport:
    def __init__(self, answers: tuple[Mapping[str, object], ...]) -> None:
        self._answers = list(answers)
        self.calls = 0

    async def follow_up(self, request: FollowUpRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_follow_up_cases(path: Path) -> tuple[str, str, tuple[FollowUpCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[FollowUpCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"follow-up case {raw['case_id']}: unknown expectation")
        if raw["kind"] not in KINDS:
            raise ValueError(f"follow-up case {raw['case_id']}: unknown kind")
        cases.append(
            FollowUpCase(
                case_id=str(raw["case_id"]),
                kind=raw["kind"],
                question=str(raw["question"]),
                answer_transcript=str(raw["answer_transcript"]),
                reference_answer=str(raw.get("reference_answer", "")),
                prior_follow_ups=tuple(str(prior) for prior in raw.get("prior_follow_ups", ())),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_follow_up_case(case: FollowUpCase, *, model: str) -> FollowUpCaseOutcome:
    transport = _ScriptedTransport(case.answers)
    service = InterviewFollowUpService(transport, model=model)
    request = FollowUpRequest(
        question=case.question,
        answer_transcript=case.answer_transcript,
        reference_answer=case.reference_answer,
        prior_follow_ups=case.prior_follow_ups,
    )
    try:
        outcome = await service.decide(request)
    except InterviewFollowUpUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        if outcome.follow_up is not None:
            observed = "follow_up"
        else:
            observed = "none" if transport.calls else "none_without_model"
    return FollowUpCaseOutcome(
        case_id=case.case_id,
        kind=case.kind,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_follow_up_cases(path: Path) -> FollowUpReport:
    model, fixture_version, cases = load_follow_up_cases(path)
    outcomes = [await run_follow_up_case(case, model=model) for case in cases]
    return FollowUpReport(model=model, fixture_version=fixture_version, outcomes=tuple(outcomes))


__all__ = [
    "INTERVIEW_FOLLOW_UP_EVALUATOR_VERSION",
    "PRESSURE_PROBE_MAX_SHARE",
    "FollowUpCase",
    "FollowUpReport",
    "load_follow_up_cases",
    "run_follow_up_cases",
]
```

Run: `~/.local/bin/uv run pytest apps/backend/tests/evals/test_interview_follow_up.py -q`
Expected: `5 passed`.

- [ ] **Step 4: Write the failing suite assertions.** In `apps/backend/tests/evals/test_suite.py` add `"interview_follow_up",` to the set in `test_the_suite_covers_speech_agents_memory_and_rubric`, add `"interview-follow-up-cases.json",` to the fixtures set and `"interview_follow_up",` to the `evaluator_versions` set in `test_provenance_names_every_fixture_model_prompt_and_rubric_by_hash_or_version`.

Run: `~/.local/bin/uv run pytest apps/backend/tests/evals/test_suite.py -q`
Expected: FAIL, the three sets are each missing the new name.

- [ ] **Step 5: Add the part to the suite.** In `apps/backend/src/tamforge_backend/evals/suite.py`:

Add the import after the `from .failure_injection import ...` line:

```python
from .interview_follow_up import INTERVIEW_FOLLOW_UP_EVALUATOR_VERSION, run_follow_up_cases
```

Add after `PRACTICE_REVIEW_REFUSALS: Final = 1.0`:

```python
INTERVIEW_FOLLOW_UP_HELD: Final = 1.0
```

In `run_suite` add after `practice_path = ...`:

```python
    follow_up_path = fixtures_dir / "interview-follow-up-cases.json"
```

add `follow_up_path,` as the last element of the tuple in the `for path in (...)` existence check and as the last element of the tuple inside `Provenance(fixtures={...})`, and add after the `practice_review` `parts.append(...)` block:

```python
    follow_ups = await run_follow_up_cases(follow_up_path)
    follow_ups_held = follow_ups.held / len(follow_ups.outcomes) if follow_ups.outcomes else 0.0
    parts.append(
        PartResult(
            "interview_follow_up",
            "held",
            round(follow_ups_held, 4),
            INTERVIEW_FOLLOW_UP_HELD,
            follow_ups.passed and follow_ups_held >= INTERVIEW_FOLLOW_UP_HELD,
            f"{len(follow_ups.outcomes)} cases against {follow_ups.model}: one question about "
            f"what was said, probes on {follow_ups.pressure_probe_share:.0%} of good answers",
        )
    )
```

and add to `evaluator_versions={...}` after the `practice_review` entry:

```python
            "interview_follow_up": INTERVIEW_FOLLOW_UP_EVALUATOR_VERSION,
```

- [ ] **Step 6: Run both evals, ruff and mypy.**

Run: `~/.local/bin/uv run pytest apps/backend/tests/evals -q`
Expected: all pass.
Run: `~/.local/bin/uv run ruff check apps/backend` then `~/.local/bin/uv run mypy apps/backend/src packages/protocol/src`
Expected: both clean.

- [ ] **Step 7: Commit.**

```bash
git add apps/backend/src/tamforge_backend/evals/interview_follow_up.py apps/backend/src/tamforge_backend/evals/suite.py apps/backend/tests/fixtures/evals/interview-follow-up-cases.json apps/backend/tests/evals/test_interview_follow_up.py apps/backend/tests/evals/test_suite.py
git commit -m "test(evals): hold follow-ups to what was said and probes to a minority" -m "Twenty-two scripted cases: invented and reference-only targets are refused, and of nine solid answers that all script a pressure probe only the gated minority ends in a follow-up." -m "Refs #390" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 5: `InterviewPracticeModel` wiring

**Files**
- Modify: `apps/macos/TAMForge/Features/Interviewer/InterviewerTurn.swift`
- Test (modify): `apps/macos/TAMForgeTests/InterviewerTurnTests.swift`
- Test (modify): `apps/macos/TAMForgeTests/RecordingFeatureTests.swift`

**Interfaces**
- Consumes: `InterviewerTurn.askFollowUp(_:)`, `InterviewerTurn.followUpsRemaining`, `RecordingCoordinator.$transcriptState`, `RecordingTranscriptState`, `SpeechTranscriptionResult.text`.
- Produces:
  - `PracticeRecording.practiceTranscript(for recordingID: UUID) async -> String?` (new protocol requirement; `RecordingCoordinator` implements it)
  - `@MainActor protocol PracticeFollowUpProviding: AnyObject { func followUp(question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]) async throws -> String? }`
  - `PracticeAnswer.followUpQuestion: String?`, `PracticeAnswer.parentRecordingID: UUID?` (both default `nil`)
  - `InterviewPracticeModel.followUpTimeout: Duration` (`.seconds(45)`), `InterviewPracticeModel.followUpsEnabledKey: String` (`"interviewer.followUpsEnabled"`)
  - `InterviewPracticeModel.init(synthesizer:recorder:followUps:followUpTimeout:defaults:shuffle:)` (the three new parameters are defaulted, so every existing call site compiles)
  - `@Published var followUpsEnabled: Bool`, `@Published private(set) var currentFollowUp: String?`, `@Published private(set) var isPreparingFollowUp: Bool`, `var spokenPrompt: String?`
  - `func considerFollowUp() async`

**Independent of:** Tasks 1, 2, 3, 4.

Design notes:
- `endAnswer()` stays what it is (stop, commit, record the answer) so the view can submit the answer at once; `considerFollowUp()` is the separate, possibly slow step. It only ever runs in `.answerCommitted`, so it cannot interrupt an answer.
- The local transcription queue has one slot and defers under memory or thermal pressure, so `practiceTranscript(for:)` may wait without bound. The model owns the bound: the whole decision (transcript plus request) races a 45 s timer, and on timeout, on a failed transcript, on a thrown request or on a `nil` reply the session is simply left in `.answerCommitted`, where "Next question" already works.
- The learner may press "Next question" while the interviewer is thinking. A request token makes the late result a no-op.
- The transcript comes from the microphone track only, so it is the learner's words and not the synthesized question.
- When a follow-up is asked the revealed reference answer is hidden again, and it cannot be revealed while the interviewer is thinking.

- [ ] **Step 1: Write the failing model tests.** In `apps/macos/TAMForgeTests/InterviewerTurnTests.swift`:

Replace the `FakePracticeRecorder` class at the bottom of the file with:

```swift
@MainActor
private final class FakePracticeRecorder: PracticeRecording {
    var refuses = false
    var transcript: String? = "I had an unhappy customer and I worked hard to improve things for them."
    var transcriptNeverArrives = false
    private(set) var ids: [UUID] = []
    private(set) var transcriptRequests: [UUID] = []
    private(set) var isPracticeRecordingActive = false
    var lastPracticeRecordingID: UUID? { ids.last }

    func beginPracticeRecording() async {
        guard !refuses else { return }
        ids.append(UUID())
        isPracticeRecordingActive = true
    }

    func endPracticeRecording() async { isPracticeRecordingActive = false }

    func practiceTranscript(for recordingID: UUID) async -> String? {
        transcriptRequests.append(recordingID)
        if transcriptNeverArrives {
            try? await Task.sleep(for: .seconds(30))
            return nil
        }
        return transcript
    }
}

@MainActor
private final class FakeFollowUps: PracticeFollowUpProviding {
    struct Request: Equatable {
        let question: String
        let referenceAnswer: String
        let transcript: String
        let priorFollowUps: [String]
    }

    var replies: [String?] = []
    var failure: (any Error)?
    var delay: Duration?
    private(set) var requests: [Request] = []

    func followUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String? {
        requests.append(Request(
            question: question, referenceAnswer: referenceAnswer,
            transcript: transcript, priorFollowUps: priorFollowUps
        ))
        if let delay { try? await Task.sleep(for: delay) }
        if let failure { throw failure }
        return replies.isEmpty ? nil : replies.removeFirst()
    }
}
```

Add these members inside `InterviewPracticeModelTests`, after `entry(...)`:

```swift
    private static let suite = "InterviewPracticeModelTests"

    private func freshDefaults() -> UserDefaults {
        let defaults = UserDefaults(suiteName: Self.suite)!
        defaults.removePersistentDomain(forName: Self.suite)
        return defaults
    }

    private func practice(
        _ recorder: FakePracticeRecorder, _ followUps: FakeFollowUps?, voice: RecordingSynthesizer = RecordingSynthesizer(),
        timeout: Duration = .seconds(5), defaults: UserDefaults? = nil
    ) -> InterviewPracticeModel {
        InterviewPracticeModel(
            synthesizer: voice, recorder: recorder, followUps: followUps, followUpTimeout: timeout,
            defaults: defaults ?? freshDefaults(), shuffle: { $0 }
        )
    }

    private func answer(_ model: InterviewPracticeModel) async {
        await model.beginAnswer()
        await model.endAnswer()
        await model.considerFollowUp()
    }

    func testAFollowUpIsSpokenAfterTheAnswerAndItsAnswerIsLinkedToTheFirst() async {
        let voice = RecordingSynthesizer()
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change for that customer?", nil]
        let model = practice(recorder, followUps, voice: voice)
        model.start(entries: [entry(1, "Q1. Tell me about a difficult customer", body: "Four anchors."), entry(2, "Q2. Why us?")])

        await model.beginAnswer()
        await model.endAnswer()
        model.revealReference()
        XCTAssertEqual(model.revealedReference, "Four anchors.")
        await model.considerFollowUp()

        XCTAssertEqual(voice.utterances, ["Tell me about a difficult customer", "What exactly did you change for that customer?"])
        XCTAssertEqual(model.currentFollowUp, "What exactly did you change for that customer?")
        XCTAssertEqual(model.spokenPrompt, "What exactly did you change for that customer?")
        XCTAssertEqual(model.progress, "Question 1 of 2")  // still the same question
        XCTAssertNil(model.revealedReference)  // no reading the reference while answering the follow-up
        XCTAssertTrue(model.canBeginAnswer)
        XCTAssertFalse(model.canMoveOn)
        XCTAssertEqual(followUps.requests.first, FakeFollowUps.Request(
            question: "Tell me about a difficult customer", referenceAnswer: "Four anchors.",
            transcript: recorder.transcript!, priorFollowUps: []
        ))
        XCTAssertEqual(recorder.transcriptRequests, [recorder.ids[0]])

        await answer(model)  // the reply to this one is nil: no second follow-up
        XCTAssertEqual(model.answers.count, 2)
        XCTAssertNil(model.answers[0].followUpQuestion)
        XCTAssertNil(model.answers[0].parentRecordingID)
        XCTAssertEqual(model.answers[1].followUpQuestion, "What exactly did you change for that customer?")
        XCTAssertEqual(model.answers[1].parentRecordingID, recorder.ids[0])
        XCTAssertEqual(model.answers[1].question, model.answers[0].question)
        XCTAssertEqual(followUps.requests[1].priorFollowUps, ["What exactly did you change for that customer?"])
        XCTAssertTrue(model.canMoveOn)

        model.next()
        XCTAssertNil(model.currentFollowUp)
        XCTAssertEqual(model.spokenPrompt, "Why us?")
    }

    func testFollowUpsStopAtTwoPerQuestionAndTheThirdIsNeverRequested() async {
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change?", "How do you know it improved?", "And then what happened?"]
        let model = practice(recorder, followUps)
        model.start(entries: [entry(1, "Q1. Tell me about a difficult customer")])

        await answer(model)
        await answer(model)
        await answer(model)

        XCTAssertEqual(followUps.requests.count, 2)
        XCTAssertEqual(model.answers.count, 3)
        XCTAssertEqual(model.answers[2].parentRecordingID, recorder.ids[1])  // a chain, not a star
        XCTAssertEqual(model.turn?.followUpsRemaining, 0)
        XCTAssertTrue(model.canMoveOn)
    }

    func testATranscriptThatNeverArrivesMovesOnAfterTheTimeout() async {
        let recorder = FakePracticeRecorder()
        recorder.transcriptNeverArrives = true
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change?"]
        let model = practice(recorder, followUps, timeout: .milliseconds(50))
        model.start(entries: [entry(1, "Q1. Why?"), entry(2, "Q2. Why us?")])

        await answer(model)

        XCTAssertTrue(followUps.requests.isEmpty)
        XCTAssertFalse(model.isPreparingFollowUp)
        XCTAssertNil(model.currentFollowUp)
        XCTAssertTrue(model.canMoveOn)
        model.next()
        XCTAssertEqual(model.spokenPrompt, "Why us?")
        XCTAssertEqual(InterviewPracticeModel.followUpTimeout, .seconds(45))
    }

    func testAFailedTranscriptOrAFailedRequestMovesOnWithoutAFollowUp() async {
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.failure = InterviewAPIError.unavailable
        let voice = RecordingSynthesizer()
        let model = practice(recorder, followUps, voice: voice)
        model.start(entries: [entry(1, "Q1. Why?"), entry(2, "Q2. Why us?")])

        await answer(model)  // the role is down: a 503 surfaces as a thrown error
        XCTAssertEqual(followUps.requests.count, 1)
        XCTAssertNil(model.currentFollowUp)
        XCTAssertNil(model.message)  // moving on is not an error the learner has to read
        XCTAssertTrue(model.canMoveOn)

        model.next()
        recorder.transcript = nil  // transcription failed, or nothing is transcribing
        followUps.failure = nil
        followUps.replies = ["What exactly did you change?"]
        await answer(model)
        XCTAssertEqual(followUps.requests.count, 1)
        XCTAssertEqual(voice.utterances, ["Why?", "Why us?"])
        XCTAssertTrue(model.canMoveOn)
    }

    func testTheSwitchTurnsFollowUpsOffAndTheChoiceIsRemembered() async {
        let defaults = freshDefaults()
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change?"]
        let model = practice(recorder, followUps, defaults: defaults)
        XCTAssertTrue(model.followUpsEnabled)  // on by default

        model.followUpsEnabled = false
        model.start(entries: [entry(1, "Q1. Why?")])
        await answer(model)
        XCTAssertTrue(followUps.requests.isEmpty)
        XCTAssertTrue(recorder.transcriptRequests.isEmpty)
        XCTAssertTrue(model.canMoveOn)

        XCTAssertEqual(defaults.object(forKey: InterviewPracticeModel.followUpsEnabledKey) as? Bool, false)
        XCTAssertFalse(practice(recorder, followUps, defaults: defaults).followUpsEnabled)
    }

    func testMovingOnWhileTheInterviewerThinksDropsTheFollowUp() async {
        let voice = RecordingSynthesizer()
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change?"]
        followUps.delay = .milliseconds(200)
        let model = practice(recorder, followUps, voice: voice)
        model.start(entries: [entry(1, "Q1. Why?"), entry(2, "Q2. Why us?")])
        await model.beginAnswer()
        await model.endAnswer()

        let thinking = Task { await model.considerFollowUp() }
        try? await Task.sleep(for: .milliseconds(40))
        XCTAssertTrue(model.isPreparingFollowUp)
        XCTAssertFalse(model.canRevealReference)
        model.next()
        await thinking.value

        XCTAssertEqual(voice.utterances, ["Why?", "Why us?"])
        XCTAssertNil(model.currentFollowUp)
        XCTAssertFalse(model.isPreparingFollowUp)
        XCTAssertTrue(model.canBeginAnswer)
    }
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests/InterviewPracticeModelTests test`
Expected: the test target fails to compile: `cannot find type 'PracticeFollowUpProviding' in scope`.

- [ ] **Step 3: Extend the protocols and the answer.** In `apps/macos/TAMForge/Features/Interviewer/InterviewerTurn.swift` replace the `PracticeRecording` protocol and the `RecordingCoordinator` extension with:

```swift
/// What free practice needs from the recorder: start, stop, the recording it made, and that
/// recording's local transcript.
@MainActor
protocol PracticeRecording: AnyObject {
    var isPracticeRecordingActive: Bool { get }
    var lastPracticeRecordingID: UUID? { get }
    func beginPracticeRecording() async
    func endPracticeRecording() async
    /// The local transcript of that recording once it is ready. Nil when transcription
    /// failed, when nothing is transcribing that recording, or when the wait is cancelled.
    /// The transcription queue has one slot and defers under memory or thermal pressure, so
    /// this may wait without bound: the caller owns the timeout.
    func practiceTranscript(for recordingID: UUID) async -> String?
}

extension RecordingCoordinator: PracticeRecording {
    var isPracticeRecordingActive: Bool { phase.isActive }
    var lastPracticeRecordingID: UUID? { lastRecordingID }
    func beginPracticeRecording() async { await start() }
    func endPracticeRecording() async { await stop() }

    func practiceTranscript(for recordingID: UUID) async -> String? {
        for await state in $transcriptState.values {
            switch state {
            case let .ready(id, result) where id == recordingID: return result.text
            case let .running(id) where id == recordingID: continue
            case let .deferred(id, _) where id == recordingID: continue
            default: return nil  // failed, idle, or the slot now belongs to another recording
            }
        }
        return nil
    }
}

/// Where the interviewer's follow-up comes from. Returns nil when there is nothing to ask;
/// throws when the role is unavailable. Either way the session moves on.
@MainActor
protocol PracticeFollowUpProviding: AnyObject {
    func followUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String?
}
```

Replace `struct PracticeAnswer` with:

```swift
struct PracticeAnswer: Equatable, Sendable, Identifiable {
    let question: PracticeQuestion
    let recordingID: UUID
    /// Set together when this answer responds to a follow-up: what the interviewer asked,
    /// and the recording of the answer it followed.
    var followUpQuestion: String? = nil
    var parentRecordingID: UUID? = nil

    var id: UUID { recordingID }
}
```

- [ ] **Step 4: Wire the model.** In the same file, in `InterviewPracticeModel`:

Replace the stored properties and `init` (from `@Published private(set) var questions` through the closing brace of `init`) with:

```swift
    /// How long the interviewer may think before the session moves on without a follow-up.
    /// It covers the local transcript, which has no bound of its own, and the request.
    nonisolated static let followUpTimeout: Duration = .seconds(45)
    nonisolated static let followUpsEnabledKey = "interviewer.followUpsEnabled"

    @Published private(set) var questions: [PracticeQuestion] = []
    @Published private(set) var turn: InterviewerTurn?
    @Published private(set) var isAnswering = false
    @Published private(set) var answers: [PracticeAnswer] = []
    @Published private(set) var revealedReference: String?
    @Published private(set) var message: String?
    /// The follow-up the learner is being asked right now, if any.
    @Published private(set) var currentFollowUp: String?
    @Published private(set) var isPreparingFollowUp = false
    /// On by default; off trades the probing for volume. Remembered across launches.
    @Published var followUpsEnabled: Bool {
        didSet { defaults.set(followUpsEnabled, forKey: Self.followUpsEnabledKey) }
    }

    private let synthesizer: any LocalSpeechSynthesizing
    private let recorder: (any PracticeRecording)?
    private let followUps: (any PracticeFollowUpProviding)?
    private let followUpTimeout: Duration
    private let defaults: UserDefaults
    private let shuffle: ([PracticeQuestion]) -> [PracticeQuestion]
    private var askedFollowUps: [String] = []
    private var followUpRequest: UUID?

    init(
        synthesizer: any LocalSpeechSynthesizing, recorder: (any PracticeRecording)?,
        followUps: (any PracticeFollowUpProviding)? = nil,
        followUpTimeout: Duration = InterviewPracticeModel.followUpTimeout,
        defaults: UserDefaults = .standard,
        shuffle: @escaping ([PracticeQuestion]) -> [PracticeQuestion] = { $0.shuffled() }
    ) {
        self.synthesizer = synthesizer
        self.recorder = recorder
        self.followUps = followUps
        self.followUpTimeout = followUpTimeout
        self.defaults = defaults
        self.shuffle = shuffle
        followUpsEnabled = defaults.object(forKey: Self.followUpsEnabledKey) as? Bool ?? true
    }
```

Replace the `canRevealReference` line and add `spokenPrompt` above it:

```swift
    /// What the interviewer last said for this question: the follow-up, or the question.
    var spokenPrompt: String? { currentFollowUp ?? current?.prompt }
    var canRevealReference: Bool {
        turn?.phase == .answerCommitted && revealedReference == nil && !isPreparingFollowUp
    }
```

In `start(entries:)` add `abandonFollowUp()` directly after `message = nil`.

Replace `repeatQuestion()` with:

```swift
    func repeatQuestion() {
        guard let spokenPrompt, !isAnswering else { return }
        synthesizer.speak(spokenPrompt)
    }
```

Replace `endAnswer()` with:

```swift
    func endAnswer() async {
        guard isAnswering, let recorder, let current else { return }
        await recorder.endPracticeRecording()
        isAnswering = false
        try? turn?.commitAnswer()
        if let id = recorder.lastPracticeRecordingID {
            // An answer to a follow-up links to the answer that follow-up was asked about.
            let parent = currentFollowUp == nil ? nil : answers.last?.recordingID
            answers.append(PracticeAnswer(
                question: current, recordingID: id,
                followUpQuestion: currentFollowUp, parentRecordingID: parent
            ))
        }
    }

    /// After a committed answer: wait for its local transcript, ask the role for a
    /// follow-up, and speak it if there is one and the limit allows. A missing transcript,
    /// a failed request, a timeout or "nothing to ask" all leave the turn committed, so the
    /// learner moves on exactly as before. Never runs while an answer is in progress.
    func considerFollowUp() async {
        guard followUpsEnabled, followUps != nil, recorder != nil,
              let turn, turn.phase == .answerCommitted, turn.followUpsRemaining > 0,
              let question = current, let answer = answers.last, answer.question == question
        else { return }
        let request = UUID()
        followUpRequest = request
        isPreparingFollowUp = true
        let prior = askedFollowUps
        let text = await Self.firstResult(within: followUpTimeout) { [weak self] in
            await self?.requestFollowUp(for: answer, prior: prior)
        }
        guard followUpRequest == request else { return }  // the learner moved on meanwhile
        followUpRequest = nil
        isPreparingFollowUp = false
        guard let text, let spoken = try? self.turn?.askFollowUp(text) else { return }
        revealedReference = nil
        currentFollowUp = spoken
        askedFollowUps.append(spoken)
        synthesizer.speak(spoken)
    }

    private func requestFollowUp(for answer: PracticeAnswer, prior: [String]) async -> String? {
        guard let recorder, let followUps,
              let transcript = await recorder.practiceTranscript(for: answer.recordingID),
              !transcript.isEmpty
        else { return nil }
        let reply = try? await followUps.followUp(
            question: answer.question.prompt, referenceAnswer: answer.question.entry.body,
            transcript: transcript, priorFollowUps: prior
        )
        let trimmed = (reply ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// The work's result, or nil once the timeout passes. Whichever loses is cancelled.
    private nonisolated static func firstResult(
        within timeout: Duration, of work: @escaping @MainActor @Sendable () async -> String?
    ) async -> String? {
        await withTaskGroup(of: String?.self) { group in
            group.addTask { await work() }
            group.addTask {
                try? await Task.sleep(for: timeout)
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first
        }
    }

    private func abandonFollowUp() {
        followUpRequest = nil
        isPreparingFollowUp = false
        currentFollowUp = nil
        askedFollowUps = []
    }
```

Replace `next()` and `stop()` with:

```swift
    func next() {
        guard canMoveOn else { return }
        abandonFollowUp()
        revealedReference = nil
        askNext()
    }

    func stop() {
        guard !isAnswering else { return }
        abandonFollowUp()
        turn?.finish()
    }
```

Update the class doc comment's last sentence to: `It never coaches and never counts as a block's attempt; each answer, including each answer to a follow-up, is an ordinary recording the speech pipeline transcribes.`

- [ ] **Step 5: Run the model tests and expect a pass.**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests/InterviewPracticeModelTests -only-testing:TAMForgeTests/InterviewerTurnTests test`
Expected: `TEST SUCCEEDED` with 17 tests executed (8 turn tests, 9 model tests). A run that reports zero tests matched nothing and is not a pass.

- [ ] **Step 6: Write the failing coordinator test.** In `apps/macos/TAMForgeTests/RecordingFeatureTests.swift`, directly after `testNoTranscriberInjectedKeepsTranscriptIdleAndNeverCallsReader`, add:

```swift
    func testPracticeTranscriptWaitsForReadyAndIsNilWhenNothingWillArrive() async throws {
        let micChunk = RecordingPCMChunk.fixture(
            track: .microphone, presentationNanoseconds: 1_000_000_000, sampleCount: 16_000
        )
        let transcribing = await MainActor.run {
            RecordingCoordinator(
                preflight: FakeRecordingPreflight(),
                source: FakeRecordingCaptureSource(),
                spoolFactory: RecoveryTrackingSpoolFactory(spool: OrderedFakeRecordingSpool()),
                audioReader: FakeRecordingAudioReader(microphoneChunks: [micChunk]),
                transcriber: FakeSealTranscriber(text: "I hit the ceiling there")
            )
        }
        await transcribing.beginPracticeRecording()
        await transcribing.endPracticeRecording()
        let recordingID = try XCTUnwrap(await MainActor.run { transcribing.lastPracticeRecordingID })
        let ready = await transcribing.practiceTranscript(for: recordingID)
        XCTAssertEqual(ready, "I hit the ceiling there")
        // The slot belongs to that recording: asking about any other one does not wait.
        let other = await transcribing.practiceTranscript(for: UUID())
        XCTAssertNil(other)

        let failing = await MainActor.run {
            RecordingCoordinator(
                preflight: FakeRecordingPreflight(),
                source: FakeRecordingCaptureSource(),
                spoolFactory: RecoveryTrackingSpoolFactory(spool: OrderedFakeRecordingSpool()),
                audioReader: FakeRecordingAudioReader(microphoneChunks: [micChunk]),
                transcriber: FakeSealTranscriber(shouldFail: true)
            )
        }
        await failing.beginPracticeRecording()
        await failing.endPracticeRecording()
        let failedID = try XCTUnwrap(await MainActor.run { failing.lastPracticeRecordingID })
        let failed = await failing.practiceTranscript(for: failedID)
        XCTAssertNil(failed)

        let silent = await MainActor.run {
            RecordingCoordinator(
                preflight: FakeRecordingPreflight(),
                source: FakeRecordingCaptureSource(),
                spoolFactory: FakeRecordingSpoolFactory(),
                audioReader: FakeRecordingAudioReader(microphoneChunks: []),
                transcriber: nil
            )
        }
        await silent.beginPracticeRecording()
        await silent.endPracticeRecording()
        let silentID = try XCTUnwrap(await MainActor.run { silent.lastPracticeRecordingID })
        let none = await silent.practiceTranscript(for: silentID)
        XCTAssertNil(none)  // nothing is transcribing: no wait at all
    }
```

This test was written after the implementation in Step 3 because the protocol requirement and its only production conformance have to land together for the target to compile; it must still be seen failing once. Temporarily change `return result.text` to `return nil` in `practiceTranscript(for:)`, run the command below and confirm `XCTAssertEqual failed: ("nil") is not equal to ("Optional("I hit the ceiling there")")`, then restore the line.

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests/RecordingFeatureTests/testPracticeTranscriptWaitsForReadyAndIsNilWhenNothingWillArrive test`
Expected after restoring: `TEST SUCCEEDED`, 1 test executed.

- [ ] **Step 7: Commit.**

```bash
git add apps/macos/TAMForge/Features/Interviewer/InterviewerTurn.swift apps/macos/TAMForgeTests/InterviewerTurnTests.swift apps/macos/TAMForgeTests/RecordingFeatureTests.swift
git commit -m "feat(macos): let the interviewer ask follow-ups after a committed answer" -m "InterviewPracticeModel waits for the local transcript, asks for a follow-up and calls askFollowUp within the limit of two. The whole decision is bounded by a 45 s timeout; a failed transcript, a failed request or a timeout leaves the session free to move on. A remembered switch turns follow-ups off." -m "Refs #390" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 6: Service call, linked submission and the SwiftUI switch

**Files**
- Modify: `apps/macos/TAMForge/Features/Interviews/InterviewService.swift`
- Modify: `apps/macos/TAMForge/Features/Interviews/InterviewsModel.swift`
- Modify: `apps/macos/TAMForge/Features/Interviews/InterviewModels.swift`
- Modify: `apps/macos/TAMForge/Features/Interviews/InterviewsView.swift`
- Test (modify): `apps/macos/TAMForgeTests/InterviewsModelTests.swift`

**Interfaces**
- Consumes (Task 5): `PracticeFollowUpProviding`, `PracticeAnswer.followUpQuestion`, `PracticeAnswer.parentRecordingID`, `InterviewPracticeModel.init(synthesizer:recorder:followUps:...)`, `considerFollowUp()`, `followUpsEnabled`, `isPreparingFollowUp`, `currentFollowUp`, `spokenPrompt`. Consumes the wire contract fixed in "Task order".
- Produces:
  - `InterviewAPI.submitPracticeAnswer(question: String, recordingID: UUID, referenceID: Int?, followUpQuestion: String?, parentRecordingID: UUID?) async throws -> PracticeAnswerReview` (replaces the three-argument requirement)
  - `InterviewAPI.practiceFollowUp(question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]) async throws -> String?`
  - `extension InterviewsModel: PracticeFollowUpProviding`
  - `PracticeAnswerReview.followUpQuestion: String?` (JSON key `follow_up_question`, absent in old payloads)
  - accessibility identifiers `practiceFollowUpsToggle`, `practiceFollowUpPending`, `practiceFollowUpContext`

**Independent of:** Tasks 1, 2, 3, 4. Depends on Task 5.

- [ ] **Step 1: Write the failing tests.** In `apps/macos/TAMForgeTests/InterviewsModelTests.swift`:

In `FakeInterviewAPI`, replace `submitPracticeAnswer(question:recordingID:referenceID:)` with the two functions below and add the two stored properties above them:

```swift
    struct Submission: Equatable {
        let recordingID: UUID
        let followUpQuestion: String?
        let parentRecordingID: UUID?
    }

    private(set) var submissions: [Submission] = []
    var followUpReply: String? = "What exactly was the ceiling?"

    func submitPracticeAnswer(
        question: String, recordingID: UUID, referenceID: Int?,
        followUpQuestion: String?, parentRecordingID: UUID?
    ) async throws -> PracticeAnswerReview {
        calls.append("submit:\(question)")
        if let failure { throw failure }
        guard uploadedRecordings.contains(recordingID) else { throw InterviewAPIError.notFound }
        submissions.append(Submission(
            recordingID: recordingID, followUpQuestion: followUpQuestion, parentRecordingID: parentRecordingID
        ))
        let status = transcribedRecordings.contains(recordingID) ? "queued" : "awaiting_transcript"
        let review = PracticeAnswerReview(
            id: 1, question: question, recordingID: recordingID, referenceMaterialID: referenceID,
            followUpQuestion: followUpQuestion, status: status,
            failureCategory: nil, dimensions: [], strengths: [], fixes: [], referenceCoverage: "", readiness: nil,
            createdAt: Date(timeIntervalSince1970: 0)
        )
        practiceStore = [review]
        return review
    }

    func practiceFollowUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String? {
        calls.append("followUp:\(question):\(priorFollowUps.count)")
        if let failure { throw failure }
        return followUpReply
    }
```

Add these tests to `InterviewsModelTests`:

```swift
    func testAFollowUpAnswerIsSubmittedWithItsQuestionAndItsParentRecording() async {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)
        let entry = ReferenceEntry(
            id: 5, kind: .answerBank, documentTitle: "bank", heading: "Q1. Why?", body: "Because.",
            readinessLabel: "", readinessVerified: false
        )
        let question = PracticeQuestion(entry: entry, prompt: "Why?")
        let first = PracticeAnswer(question: question, recordingID: UUID())
        let second = PracticeAnswer(
            question: question, recordingID: UUID(),
            followUpQuestion: "What exactly was the ceiling?", parentRecordingID: first.recordingID
        )
        api.uploadedRecordings = [first.recordingID, second.recordingID]

        await model.submitPracticeAnswer(first)
        await model.submitPracticeAnswer(second)

        XCTAssertTrue(model.unsentPracticeAnswers.isEmpty)
        XCTAssertEqual(api.submissions.first, .init(recordingID: first.recordingID, followUpQuestion: nil, parentRecordingID: nil))
        XCTAssertTrue(api.submissions.contains(.init(
            recordingID: second.recordingID, followUpQuestion: "What exactly was the ceiling?",
            parentRecordingID: first.recordingID
        )))
    }

    func testTheFollowUpRequestGoesThroughTheAPIAndAnUnavailableRoleThrows() async throws {
        let api = FakeInterviewAPI(records: [])
        let model = InterviewsModel(api: api)
        let provider: any PracticeFollowUpProviding = model

        let asked = try await provider.followUp(
            question: "Why?", referenceAnswer: "Because.", transcript: "I hit the ceiling there.",
            priorFollowUps: ["Why now?"]
        )
        XCTAssertEqual(asked, "What exactly was the ceiling?")
        XCTAssertEqual(api.calls.last, "followUp:Why?:1")

        api.failure = .unavailable
        do {
            _ = try await provider.followUp(question: "Why?", referenceAnswer: "", transcript: "x", priorFollowUps: [])
            XCTFail("an unavailable role must throw so the practice moves on")
        } catch {
            XCTAssertEqual(error as? InterviewAPIError, .unavailable)
        }
        XCTAssertNil(model.errorMessage)  // a missing follow-up is not an error on the screen
    }

    func testAReviewOfAFollowUpAnswerDecodesItsQuestionAndOldPayloadsStillDecode() throws {
        let json = """
        {"id": 5, "question": "Why?", "recording_id": "10F3D9DE-B6DD-48A4-8F01-BD570E17DE22",
         "reference_material_id": null, "follow_up_of": 4, "follow_up_question": "What was the ceiling?",
         "status": "ready", "failure_category": null, "model": "claude-fable-5-1",
         "dimensions": [{"slug": "follow_up_handling", "name": "Follow-up handling: answers what was asked and adds to the first answer",
                         "score": "3.0", "evidence": "renewed for two years", "note": "Answers what was asked."}],
         "strengths": [], "fixes": [], "reference_coverage": "", "readiness": "drilling",
         "created_at": "2026-09-18T00:00:00Z", "reviewed_at": "2026-09-18T00:05:00Z"}
        """
        let review = try NativeJSONCodec.decode(PracticeAnswerReview.self, from: Data(json.utf8))
        XCTAssertEqual(review.followUpQuestion, "What was the ceiling?")
        XCTAssertEqual(review.dimensions.first?.slug, "follow_up_handling")
    }
```

The existing `testAPracticeReviewDecodesScoresSentAsStrings` payload has no `follow_up_question` key and must keep passing unchanged: that is the "old payloads still decode" half.

- [ ] **Step 2: Run them and watch them fail.**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests/InterviewsModelTests test`
Expected: the test target fails to compile: `type 'FakeInterviewAPI' does not conform to protocol 'InterviewAPI'` and `extra argument 'followUpQuestion' in call`.

- [ ] **Step 3: Extend the API.** In `apps/macos/TAMForge/Features/Interviews/InterviewService.swift`:

In `protocol InterviewAPI` replace the `submitPracticeAnswer` requirement with:

```swift
    func submitPracticeAnswer(
        question: String, recordingID: UUID, referenceID: Int?,
        followUpQuestion: String?, parentRecordingID: UUID?
    ) async throws -> PracticeAnswerReview
    func practiceFollowUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String?
```

In `LiveInterviewAPI` replace `submitPracticeAnswer` with:

```swift
    func submitPracticeAnswer(
        question: String, recordingID: UUID, referenceID: Int?,
        followUpQuestion: String?, parentRecordingID: UUID?
    ) async throws -> PracticeAnswerReview {
        var payload: [String: Any] = ["question": question, "recording_id": recordingID.uuidString.lowercased()]
        if let referenceID { payload["reference_material_id"] = referenceID }
        // Both or neither: the server refuses a follow-up answer without its parent.
        if let followUpQuestion, let parentRecordingID {
            payload["follow_up_question"] = followUpQuestion
            payload["follow_up_of_recording_id"] = parentRecordingID.uuidString.lowercased()
        }
        let body = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        return try await request(.post, path: "/api/v1/practice-answers", body: body, as: PracticeAnswerReview.self)
    }

    /// One synchronous decision on the server. A 503 (Claude disabled, runtime failure)
    /// throws `.unavailable`; the practice session treats any throw as "no follow-up".
    func practiceFollowUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String? {
        struct Decision: Decodable, Sendable {
            let followUp: String?
            enum CodingKeys: String, CodingKey { case followUp = "follow_up" }
        }
        let body = try JSONSerialization.data(
            withJSONObject: [
                "question": question, "reference_answer": referenceAnswer,
                "transcript": transcript, "prior_follow_ups": priorFollowUps,
            ] as [String: Any],
            options: [.sortedKeys]
        )
        return try await request(
            .post, path: "/api/v1/practice-answers/follow-up", body: body, as: Decision.self
        ).followUp
    }
```

- [ ] **Step 4: Decode the follow-up question.** In `apps/macos/TAMForge/Features/Interviews/InterviewModels.swift`, in `PracticeAnswerReview`, add after `let referenceMaterialID: Int?`:

```swift
    /// What the interviewer asked, when this answer responds to a follow-up.
    let followUpQuestion: String?
```

and add to `CodingKeys` after `case referenceMaterialID = "reference_material_id"`:

```swift
        case followUpQuestion = "follow_up_question"
```

Then find every other memberwise construction and add the argument `followUpQuestion: nil` after `referenceMaterialID:`:

Run: `grep -rn "PracticeAnswerReview(" apps/macos/TAMForge apps/macos/TAMForgeTests`
Expected: only the call inside `FakeInterviewAPI` from Step 1, which already passes it.

- [ ] **Step 5: Submit the link and provide follow-ups.** In `apps/macos/TAMForge/Features/Interviews/InterviewsModel.swift`, in `refreshPracticeReviews()`, replace the two `submitPracticeAnswer` calls with:

```swift
            for answer in self.unsentPracticeAnswers {
                _ = try await self.api.submitPracticeAnswer(
                    question: answer.question.prompt, recordingID: answer.recordingID,
                    referenceID: answer.question.entry.id,
                    followUpQuestion: answer.followUpQuestion, parentRecordingID: answer.parentRecordingID
                )
                self.unsentPracticeAnswers.removeAll { $0 == answer }
            }
            let listed = try await self.api.practiceAnswers()
            for waiting in listed where waiting.isWaiting {
                // A retry for a stored answer: the server ignores everything but the recording.
                _ = try await self.api.submitPracticeAnswer(
                    question: waiting.question, recordingID: waiting.recordingID,
                    referenceID: waiting.referenceMaterialID,
                    followUpQuestion: nil, parentRecordingID: nil
                )
            }
```

The unsent list is ordered, so a follow-up answer is always sent after the answer it followed; if the parent is still uploading the loop throws on the parent and the child waits for the next refresh.

At the end of the file add:

```swift
/// The practice interviewer asks the server for its follow-ups through the same API. Errors
/// are thrown to the caller and never shown: no follow-up is a normal way for a turn to end.
extension InterviewsModel: PracticeFollowUpProviding {
    func followUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String? {
        try await api.practiceFollowUp(
            question: question, referenceAnswer: referenceAnswer,
            transcript: transcript, priorFollowUps: priorFollowUps
        )
    }
}
```

- [ ] **Step 6: Run the model tests and expect a pass.**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests/InterviewsModelTests test`
Expected: `TEST SUCCEEDED` with a non-zero test count that includes the three new tests.

- [ ] **Step 7: Wire the view.** In `apps/macos/TAMForge/Features/Interviews/InterviewsView.swift`:

In `init`, replace the `InterviewPracticeModel(...)` construction with:

```swift
            wrappedValue: InterviewPracticeModel(
                synthesizer: SystemSpeechSynthesizer(), recorder: coordinator, followUps: model
            )
```

In `practiceSection`, directly inside `VStack(alignment: .leading, spacing: 10) {` and before `if let question = practice.current {`, add:

```swift
                Toggle("Follow-up questions", isOn: $practice.followUpsEnabled)
                    .toggleStyle(.switch)
                    .font(Organic.Font.figtree(.regular, size: 13))
                    .foregroundStyle(Organic.Color.body)
                    .accessibilityIdentifier("practiceFollowUpsToggle")
                Text("On: after an answer the interviewer may ask up to two follow-ups, each after a wait of about ten seconds, on weak spots and sometimes on good answers too. Off: straight to the next question.")
                    .font(Organic.Font.figtree(.regular, size: 11))
                    .foregroundStyle(Organic.Color.muted)
```

Replace

```swift
                    Text(question.prompt).font(.title3).textSelection(.enabled)
                        .accessibilityIdentifier("practiceQuestion")
```

with

```swift
                    Text(practice.spokenPrompt ?? question.prompt).font(.title3).textSelection(.enabled)
                        .accessibilityIdentifier("practiceQuestion")
                    if practice.currentFollowUp != nil {
                        Text("Follow-up to: \(question.prompt)")
                            .font(Organic.Font.figtree(.regular, size: 11))
                            .foregroundStyle(Organic.Color.muted)
                            .accessibilityIdentifier("practiceFollowUpContext")
                    }
```

Replace the body of the `Button("Stop, that is my answer")` action with:

```swift
                                Task {
                                    await practice.endAnswer()
                                    guard let answer = practice.answers.last else { return }
                                    // The answer goes to the server now; the interviewer thinks meanwhile.
                                    Task { await model.submitPracticeAnswer(answer) }
                                    await practice.considerFollowUp()
                                }
```

In the `else if practice.canMoveOn {` branch, after the `Button("Next question")` and its identifier, add:

```swift
                            if practice.isPreparingFollowUp {
                                Text("The interviewer is thinking about a follow-up. You can move on.")
                                    .font(Organic.Font.figtree(.regular, size: 11))
                                    .foregroundStyle(Organic.Color.muted)
                                    .accessibilityIdentifier("practiceFollowUpPending")
                            }
```

Change the button `Button("Repeat the question") { practice.repeatQuestion() }` label to `Button(practice.currentFollowUp == nil ? "Repeat the question" : "Repeat the follow-up") { practice.repeatQuestion() }`.

In `practiceReviews`, directly after the closing brace of the `HStack(alignment: .firstTextBaseline) { Text(review.question)... }` row, add:

```swift
                    if let followUp = review.followUpQuestion {
                        Text("Follow-up: \(followUp)")
                            .font(Organic.Font.figtree(.regular, size: 11))
                            .foregroundStyle(Organic.Color.body)
                    }
```

- [ ] **Step 8: Build, run the whole unit target, and check the identifier contract.**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests test`
Expected: `TEST SUCCEEDED`, non-zero test count, no concurrency diagnostics.
Run: `git diff --stat origin/main -- apps/macos/TAMForgeUITests/`
Expected: empty output.
Run: `grep -rn "LazyVStack(\|LazyHStack(\|LazyVGrid(" apps/macos/TAMForge/`
Expected: no output.
Do not run `TAMForgeUITests` locally. The UI fixtures answer an unknown path with an error and start no transcriber, so in the `native-ui` job a practice answer simply gets no follow-up.

- [ ] **Step 9: Commit.**

```bash
git add apps/macos/TAMForge/Features/Interviews/InterviewService.swift apps/macos/TAMForge/Features/Interviews/InterviewsModel.swift apps/macos/TAMForge/Features/Interviews/InterviewModels.swift apps/macos/TAMForge/Features/Interviews/InterviewsView.swift apps/macos/TAMForgeTests/InterviewsModelTests.swift
git commit -m "feat(macos): follow-up switch, request and linked practice answers" -m "The Interviews screen gets a remembered follow-up switch, asks the server for each follow-up, shows the follow-up in place of the question, and submits each follow-up answer linked to the answer it followed." -m "Refs #390" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 7: Contract regeneration

**Files**
- Modify (generated): `apps/macos/TAMForge/openapi.yaml`
- Modify: `scripts/ci/tests/test_check_openapi.py` (`FROZEN_OPENAPI_SHA256`)

**Interfaces**
- Consumes: the route from Task 2 and the wire fields from Task 3.
- Produces: a native contract that matches FastAPI's schema, and the frozen hash that guards it.

**Independent of:** Tasks 4, 5, 6. Depends on Tasks 2 and 3.

- [ ] **Step 1: Watch the drift guards fail.**

Run: `~/.local/bin/uv run python scripts/ci/check_openapi.py`
Expected: non-zero exit, with the hint `Regenerate it with: uv run python scripts/ci/check_openapi.py --write`.
Run: `~/.local/bin/uv run pytest scripts/ci/tests/test_check_openapi.py -q`
Expected: `test_normalized_fastapi_schema_matches_frozen_contract` fails on the hash.

- [ ] **Step 2: Regenerate the native contract.**

Run: `~/.local/bin/uv run python scripts/ci/check_openapi.py --write`
Then: `git diff --stat -- apps/macos/TAMForge/openapi.yaml`
Expected: exactly that one file changed.

- [ ] **Step 3: Check that no OpenAPI 3.1-only construct reached the native file.** The Swift generator cannot parse a bare null type.

Run: `grep -c '"type":"null"' apps/macos/TAMForge/openapi.yaml`
Expected: `0` (grep exits 1 on a zero count; that is the passing result here).
Run: `grep -o '"/api/v1/practice-answers/follow-up"' apps/macos/TAMForge/openapi.yaml`
Expected: one match.

- [ ] **Step 4: Freeze the new hash.**

Run:

```bash
~/.local/bin/uv run python - <<'PY'
import hashlib
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("check_openapi", pathlib.Path("scripts/ci/check_openapi.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(hashlib.sha256(module.normalized_openapi_document()).hexdigest())
PY
```

Copy the 64 hexadecimal characters it prints into `FROZEN_OPENAPI_SHA256` in `scripts/ci/tests/test_check_openapi.py`, replacing `76ac3042b5a49235718d4d99cd29a1d1928604bd72c0b20eb5897569e9ba9a3b`.

- [ ] **Step 5: Run the guards and the native build.**

Run: `~/.local/bin/uv run python scripts/ci/check_openapi.py` then `~/.local/bin/uv run pytest scripts/ci/tests/test_check_openapi.py -q`
Expected: exit 0, then all pass.
Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build`
Expected: `BUILD SUCCEEDED` (the generator plugin parses the regenerated contract).

- [ ] **Step 6: Run the full verify gate.** Every command under "Commands CI runs" except the `native-ui` pair, plus the issue's `~/.local/bin/uv run pytest apps/backend/tests -q -k practice`. All green, each run on its own line so no exit code is masked.

- [ ] **Step 7: Commit.**

```bash
git add apps/macos/TAMForge/openapi.yaml scripts/ci/tests/test_check_openapi.py
git commit -m "chore(contract): regenerate the native OpenAPI contract for practice follow-ups" -m "Refs #390" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

**Acceptance criteria of issue #390, each mapped to a task**

| Criterion | Where |
|---|---|
| New role `interview_follow_up`: question, reference answer, transcribed answer and prior follow-ups in; no follow-up or one short spoken-style question with its reason out; tool-less, structured output, bounded length | Task 1 (`FollowUpRequest`, `FollowUpOutcome`, `validate_follow_up`: one `?`, 30 words, 240 characters; `AgentSdkRuntime.follow_up` through the shared tool-less `_structured`) |
| `InterviewPracticeModel` transcribes locally, requests a follow-up and calls `askFollowUp` within the limit of two; a role failure or timeout moves on without blocking | Task 5 (`practiceTranscript(for:)`, `considerFollowUp()`, `followUpTimeout`, tests for the limit, the timeout, the failed request, the failed transcript and moving on meanwhile); Task 2 turns every server failure into a 503 the Mac reads as a throw |
| A session switch turns follow-ups off; the choice is remembered | Task 5 (`followUpsEnabled` + `UserDefaults`, test), Task 6 (the `Toggle`) |
| The question, its follow-ups and their answers are submitted together; `practice_review` gains a follow-up handling dimension, prompt version bumped, answers without follow-ups review as before | Task 3 (columns, command, service, `FOLLOW_UP_DIMENSION`, `v2`, the unchanged three-dimension path and the still-passing `follow-up-dimension-scored` refusal), Task 6 (linked submission from the Mac) |
| Prompt registered with a version; one eval checks follow-ups target something said and probes appear on a minority of good answers | Task 1 (`INTERVIEW_FOLLOW_UP_PROMPT_KEY` / `_VERSION` / `_SCHEMA_ID` pinned on `PreparedAgentRun`), Task 4 (eval, fixture, suite part) |
| Verification: macOS unit tests including the failure path; `uv run pytest apps/backend/tests -q -k practice`; both evals pass | Tasks 5 and 6; Task 3 Step 14; Task 3 Step 5 and Task 4 Step 6 |
| Decision: never interrupt an answer | Task 5 (`considerFollowUp` guards on `.answerCommitted`; `InterviewerTurn.askFollowUp` already throws otherwise) |

**Placeholder scan.** No "TBD", no "similar to Task N", no "add error handling" without code. The one value that cannot be written in advance is the new `FROZEN_OPENAPI_SHA256`: it is a hash of the generated schema, so Task 7 Step 4 gives the exact command that prints it.

**Type and name consistency, checked across tasks.**
- Wire: `transcript` and `prior_follow_ups` in `FollowUpCommand` (Task 2) are the keys `LiveInterviewAPI.practiceFollowUp` sends (Task 6); `follow_up_question` and `follow_up_of_recording_id` in `PracticeAnswerCommand` (Task 3) are the keys `submitPracticeAnswer` sends (Task 6); `follow_up_question` in `PracticeAnswerResponse` (Task 3) is the key `PracticeAnswerReview` decodes (Task 6).
- Python: `FollowUpRequest.answer_transcript` is used by the role, the route mapping, the SDK test and the eval; the transport method is `follow_up` everywhere (`FollowUpTransport`, `AgentSdkRuntime`, `_ScriptedTransport`, the unit-test `_Transport`); `validate_practice_review(..., follow_up: bool)` and `dimensions_for(*, follow_up: bool)` share the keyword.
- Swift: `PracticeFollowUpProviding.followUp(question:referenceAnswer:transcript:priorFollowUps:)` has the same labels in the protocol (Task 5), `FakeFollowUps` (Task 5) and the `InterviewsModel` extension (Task 6); `InterviewAPI.practiceFollowUp` has the same labels in the protocol, `LiveInterviewAPI` and `FakeInterviewAPI`.
- Limits agree: `MAX_FOLLOW_UPS = 2` (role), `prior_follow_ups` `max_length=2` (command), `InterviewerTurn.maxFollowUps = 2` (Mac); 30 s role wall time sits inside the Mac's 45 s.
- Migration id `20260918_0035_follow_ups` is 24 characters and the head constant in `test_curriculum_schema.py` names it.

**Fixed inline during the review.**
- The role's run-key digest and the review's digest were single expressions over 100 columns; both now build a `key` string first.
- `PracticeReviewRequest(**context)` with a `dict[str, str]` would fail `mypy --strict` against the non-string `repair_errors` parameter; `process` uses three named variables instead.
- The first draft awaited the follow-up inside `endAnswer()`, which would have delayed the answer's submission by up to 45 s; `considerFollowUp()` is separate and the view submits first.
- The first draft named the migration `20260918_0035_practice_follow_ups` (33 characters); shortened.
- A follow-up row's review could have been queued before the earlier answer had a server-side transcript and then parked as invalid input; `submit` now holds it at `awaiting_transcript` until both exist, and the integration test covers it.
