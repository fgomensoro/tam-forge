# Attestation Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Claude disabled until a current model-improvement-off attestation and subscription-policy acknowledgement are stored, and make the absence of that evidence fail closed.

**Architecture:** The attestation is an append-only provenance row on the same `Record` base as prompt versions and model runs, so it cannot be rewritten. Currency is a comparison against the policy version the code expects, not a clock. `CLAUDE_ENABLED=false` stays a valid, healthy configuration so every non-Claude study path keeps working.

**Tech Stack:** Python 3.12, Pydantic v2 and pydantic-settings, SQLAlchemy 2 async, Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-attestation-gate-design.md`

## Global Constraints

- Issue #104 (E9-I02). Backend only. Do NOT touch `apps/macos`, `speech`, or `recordings`.
- This opens the chain #104 → #65 → #66. Create the base that those extend; do NOT implement the compatibility probe (#65) or the API-credential rejection and no-paid-fallback policy (#66). Both will extend the files this plan creates.
- **No secret ever appears** in `repr`, in a validation error, in a route response, or in a log. No endpoint accepts or returns a Claude token. This slice stores no token at all.
- **Alembic revision ids must be 32 characters or fewer.** `alembic_version.version_num` is `varchar(32)` and a longer id fails on the version bookkeeping, not on the DDL. Use `20260909_0017_attestations` (26).
- Adding a migration moves the head asserted by `test_curriculum_schema.py::test_alembic_has_exactly_one_linear_head`. Update that constant; it is an inevitable consequence, not a defect.
- Do NOT add keys to the model-run header. `tamforge_provenance_insert` allowlists that key set by table name and its SQL is frozen. The new table gets only the `trg_*_immutable` trigger, exactly like `analysis_publications` in `20260908_0016_publications.py`, which is the closest precedent to copy.
- New Pydantic models subclass the existing `Contract` base in `agents/contracts.py`.
- ruff line length 100; mypy strict over `apps/backend/src`.
- uv is not on PATH: use `/Users/frank/.local/bin/uv`, and ALWAYS pass `--no-sync`. If imports fail at collection, repair with `/Users/frank/.local/bin/uv sync --all-packages --all-extras --reinstall-package tamforge-backend --reinstall-package tamforge-protocol`.
- Never run `make check` or `xcodebuild`.

---

### Task 1: The attestation record

**Files:**
- Modify: `apps/backend/src/tamforge_backend/agents/models.py`
- Create: `apps/backend/alembic/versions/20260909_0017_attestations.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py`
- Test: `apps/backend/tests/unit/agents/test_attestation_model.py`

**Interfaces:**
- Consumes: the `Record` base, `_checks` helper and `RECORD_TYPES` tuple in `agents/models.py`.
- Produces: `PrivacyAttestation`, added to `RECORD_TYPES`. Task 3 reads this table.

Read `20260908_0016_publications.py` and the `AnalysisPublication` model before writing either. This table follows the same shape: a generated column projected out of `canonical_json`, the shared check constraints, and only the immutability trigger.

Unlike `AnalysisPublication`, this row hangs off the owner, not off a model run, so it extends `Record` directly rather than `RunChild`.

- [ ] **Step 1: Write the failing model and migration tests**

Create `apps/backend/tests/unit/agents/test_attestation_model.py`:

```python
"""Shape and immutability wiring for the stored privacy attestation."""

from __future__ import annotations

from pathlib import Path

MIGRATION = Path("apps/backend/alembic/versions/20260909_0017_attestations.py")


def test_attestation_is_registered_as_immutable_provenance():
    from tamforge_backend.agents.models import RECORD_TYPES, PrivacyAttestation

    assert PrivacyAttestation in RECORD_TYPES


def test_one_current_attestation_per_owner_and_policy_version():
    from tamforge_backend.agents.models import PrivacyAttestation

    table = PrivacyAttestation.__table__
    assert table.name == "privacy_attestations"
    unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("owner_id", "policy_version") in unique


def test_migration_chains_onto_the_current_head_and_guards_immutability():
    root = Path(__file__).resolve().parents[5]
    source = (root / MIGRATION).read_text()
    assert "CREATE TABLE privacy_attestations" in source
    assert "trg_privacy_attestations_immutable" in source
    assert 'down_revision = "20260908_0016_publications"' in source
    assert 'revision = "20260909_0017_attestations"' in source
    assert len("20260909_0017_attestations") <= 32
```

Before writing this, confirm `parents[5]` reaches the repository root from `apps/backend/tests/unit/agents/`, and confirm `20260908_0016_publications` is still the head by checking that no other file under `apps/backend/alembic/versions/` names it as `down_revision`. If either is wrong, correct it and say so in your report; an earlier plan in this repository got the parent count wrong.

- [ ] **Step 2: Run to verify RED**

Run: `/Users/frank/.local/bin/uv run --no-sync pytest apps/backend/tests/unit/agents/test_attestation_model.py -q`
Expected: FAIL with `ImportError: cannot import name 'PrivacyAttestation'`.

- [ ] **Step 3: Add the model**

In `apps/backend/src/tamforge_backend/agents/models.py`, after `AnalysisPublication`:

```python
class PrivacyAttestation(Record):
    """The learner's own record that model improvement is off for a policy version."""

    __tablename__ = "privacy_attestations"
    __table_args__ = _checks("privacy_attestations", limit=16384) + (
        UniqueConstraint(
            "owner_id", "policy_version", name="uq_privacy_attestations_owner_policy"
        ),
        CheckConstraint(
            "policy_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'",
            name="policy_version_safe",
        ),
    )
    policy_version: Mapped[str] = mapped_column(
        Text,
        Computed("canonical_json::jsonb->>'policy_version'", persisted=True),
        nullable=False,
    )
```

Add `PrivacyAttestation` to `RECORD_TYPES`.

- [ ] **Step 4: Write the migration**

Create `apps/backend/alembic/versions/20260909_0017_attestations.py`, copying the structure of `20260908_0016_publications.py` exactly, including its constraint naming. The table's columns are the `Record` base's (`id`, `owner_id`, `canonical_json`, `content_hash`, `hash_format`, `created_at`) plus the generated `policy_version`. Its foreign key is to `owners (id)` only; there is no run to reference. Bound `canonical_json` to 16384 bytes. Give it only the immutability trigger, never `tamforge_provenance_insert`.

Then update the head constant in `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py::test_alembic_has_exactly_one_linear_head` to `"20260909_0017_attestations (head)"`.

- [ ] **Step 5: Verify and commit**

```bash
/Users/frank/.local/bin/uv run --no-sync pytest apps/backend/tests/unit/agents apps/backend/tests/unit/roadmaps -q
/Users/frank/.local/bin/uv run --no-sync ruff check .
/Users/frank/.local/bin/uv run --no-sync mypy apps/backend/src
```

Then stop. The controller commits.

---

### Task 2: Fail-closed settings and the policy version

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/settings.py`
- Modify: `apps/backend/src/tamforge_backend/config.py`
- Test: `apps/backend/tests/unit/agents/test_settings.py`

**Interfaces:**
- Consumes: the `Settings` class and its `_FIELD_ENV_ALIASES` map in `config.py`. Read both fully before editing; every field there has an explicit `TAMFORGE_`-prefixed alias, and the new one must follow that convention.
- Produces: `EXPECTED_POLICY_VERSION`, `AttestationRecord`, `attestation_is_current`, `ClaudeDisabled`, and `claude_availability`. Task 3 imports all of them. #65 and #66 will extend this module.

- [ ] **Step 1: Write the failing settings tests**

Create `apps/backend/tests/unit/agents/test_settings.py`:

```python
"""Claude stays off unless a current attestation says otherwise."""

from __future__ import annotations

import pytest


def attestation(**overrides):
    from tamforge_backend.agents.settings import EXPECTED_POLICY_VERSION, AttestationRecord

    data = {
        "policy_version": EXPECTED_POLICY_VERSION,
        "model_improvement_disabled": True,
        "subscription_policy_acknowledged": True,
    }
    data.update(overrides)
    return AttestationRecord.model_validate(data)


def test_a_matching_attestation_is_current():
    from tamforge_backend.agents.settings import attestation_is_current

    assert attestation_is_current(attestation()) is True


def test_an_attestation_for_another_policy_version_is_stale():
    from tamforge_backend.agents.settings import attestation_is_current

    assert attestation_is_current(attestation(policy_version="superseded-v0")) is False


@pytest.mark.parametrize(
    "field", ["model_improvement_disabled", "subscription_policy_acknowledged"]
)
def test_both_claims_must_be_affirmative(field):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        attestation(**{field: False})


def test_missing_attestation_disables_claude_rather_than_defaulting_on():
    from tamforge_backend.agents.settings import claude_availability

    status, reason = claude_availability(enabled=True, stored=None)
    assert status == "disabled"
    assert reason == "attestation_missing"


def test_a_stale_attestation_disables_claude():
    from tamforge_backend.agents.settings import claude_availability

    status, reason = claude_availability(
        enabled=True, stored=attestation(policy_version="superseded-v0")
    )
    assert status == "disabled"
    assert reason == "attestation_superseded"


def test_claude_off_by_configuration_is_not_an_error():
    from tamforge_backend.agents.settings import claude_availability

    assert claude_availability(enabled=False, stored=None) == ("disabled", "not_enabled")
    assert claude_availability(enabled=False, stored=attestation()) == (
        "disabled",
        "not_enabled",
    )


def test_enabled_with_a_current_attestation_is_ready():
    from tamforge_backend.agents.settings import claude_availability

    assert claude_availability(enabled=True, stored=attestation()) == ("ready", "none")


def test_the_application_starts_with_claude_disabled():
    from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings

    settings = Settings(
        environment="test",
        github_user_id=APPROVED_GITHUB_USER_ID,
        secure_cookies=False,
        _env_file=None,
    )
    assert settings.claude_enabled is False


def test_reasons_are_machine_only_slugs():
    import re

    from tamforge_backend.agents.settings import DISABLED_REASONS

    assert all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item) for item in DISABLED_REASONS)
```

- [ ] **Step 2: Run to verify RED**

Run: `/Users/frank/.local/bin/uv run --no-sync pytest apps/backend/tests/unit/agents/test_settings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tamforge_backend.agents.settings'`.

- [ ] **Step 3: Implement**

Create `apps/backend/src/tamforge_backend/agents/settings.py`:

```python
"""Claude is off unless stored evidence says it may run. Absence is never permission."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from .contracts import Contract, InvalidProvenance

# The Anthropic data policy version this build expects. Bump it when the policy
# changes; every earlier attestation stops being current at that moment, which is
# what the runbook's policy check exists to catch.
EXPECTED_POLICY_VERSION = "anthropic-data-policy-2026-09"

DISABLED_REASONS = (
    "not_enabled",
    "attestation_missing",
    "attestation_superseded",
)


class ClaudeDisabled(InvalidProvenance):
    """Claude was enabled without current stored evidence permitting it."""


class AttestationRecord(Contract):
    """Both claims are affirmative by construction; a negative one is not an attestation."""

    policy_version: str
    model_improvement_disabled: bool
    subscription_policy_acknowledged: bool

    @model_validator(mode="after")
    def affirmative(self) -> Self:
        if not (self.model_improvement_disabled and self.subscription_policy_acknowledged):
            raise ValueError("an attestation asserts both claims or is not one")
        return self


def attestation_is_current(record: AttestationRecord) -> bool:
    return record.policy_version == EXPECTED_POLICY_VERSION


def claude_availability(
    *, enabled: bool, stored: AttestationRecord | None
) -> tuple[Literal["disabled", "ready"], str]:
    """Report status and a machine-only reason. Never raises, never names a secret."""
    if not enabled:
        return "disabled", "not_enabled"
    if stored is None:
        return "disabled", "attestation_missing"
    if not attestation_is_current(stored):
        return "disabled", "attestation_superseded"
    return "ready", "none"
```

Then add to `config.py`'s `Settings`: a `claude_enabled: bool = False` field, and its entry in `_FIELD_ENV_ALIASES` as `"claude_enabled": "TAMFORGE_CLAUDE_ENABLED"`. Follow whatever declaration style the neighbouring boolean fields use.

- [ ] **Step 4: Verify and stop**

```bash
/Users/frank/.local/bin/uv run --no-sync pytest -m "not integration" -q
/Users/frank/.local/bin/uv run --no-sync ruff check .
/Users/frank/.local/bin/uv run --no-sync mypy apps/backend/src packages/protocol/src
/Users/frank/.local/bin/uv run --no-sync python scripts/ci/check_openapi.py
```

The OpenAPI check matters: adding a settings field must not change the generated schema. If it does, stop and report rather than regenerating.

---

### Task 3: Reading the stored attestation, and the runbook

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/compatibility.py`
- Create: `docs/runbooks/claude-subscription.md`
- Test: `apps/backend/tests/unit/agents/test_compatibility.py`

**Interfaces:**
- Consumes: `PrivacyAttestation` (Task 1) and everything Task 2 produced.
- Produces: `AttestationRepository` with a `current` method, and `claude_status`. #65 extends this module with the SDK, login and model probe.

Keep this minimal. The probe that checks the installed SDK, the subscription login, the resolved model and a typed tool round-trip is #65's work, not yours. Do not stub it, do not leave a placeholder for it.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/agents/test_compatibility.py`:

```python
"""Status derived from what is stored, with no database in the unit path."""

from __future__ import annotations

import pytest


class StubRepository:
    def __init__(self, record=None):
        self.record = record

    async def current(self, *, owner_id: int):
        return self.record


def attestation(**overrides):
    from tamforge_backend.agents.settings import EXPECTED_POLICY_VERSION, AttestationRecord

    data = {
        "policy_version": EXPECTED_POLICY_VERSION,
        "model_improvement_disabled": True,
        "subscription_policy_acknowledged": True,
    }
    data.update(overrides)
    return AttestationRecord.model_validate(data)


@pytest.mark.parametrize(
    "enabled,record,expected",
    [
        (False, None, ("disabled", "not_enabled")),
        (True, None, ("disabled", "attestation_missing")),
        (True, "stale", ("disabled", "attestation_superseded")),
        (True, "current", ("ready", "none")),
    ],
)
def test_status_reflects_configuration_and_stored_evidence(enabled, record, expected):
    import asyncio

    from tamforge_backend.agents.compatibility import claude_status

    stored = {
        None: None,
        "stale": attestation(policy_version="superseded-v0"),
        "current": attestation(),
    }[record]
    result = asyncio.run(
        claude_status(repository=StubRepository(stored), owner_id=1, enabled=enabled)
    )
    assert result == expected


def test_status_never_reports_a_token_or_free_text():
    import asyncio

    from tamforge_backend.agents.compatibility import claude_status
    from tamforge_backend.agents.settings import DISABLED_REASONS

    _, reason = asyncio.run(
        claude_status(repository=StubRepository(None), owner_id=1, enabled=True)
    )
    assert reason in DISABLED_REASONS
```

- [ ] **Step 2: Run to verify RED, then implement**

`claude_status` loads the current attestation through the repository and delegates the decision to `claude_availability`. `AttestationRepository.current` selects the newest `PrivacyAttestation` row for the owner, passes it through `verified()` from `prompt_registry` exactly as the other provenance readers do, parses its `canonical_json` into an `AttestationRecord`, and returns `None` when there is no row. A row whose stored JSON no longer parses is treated as no attestation, because a broken attestation is not permission.

- [ ] **Step 3: Write the runbook**

Create `docs/runbooks/claude-subscription.md`, matching the tone and structure of `docs/runbooks/model-provenance.md`. It must state: run `claude setup-token` locally through Anthropic's browser flow; never paste the token into chat, GitHub or the TAM Forge UI; install it as a root-owned service credential; record the one-year rotation date; confirm data-model-improvement is off; verify the current official subscription and Agent SDK policy; bump `EXPECTED_POLICY_VERSION` when that policy changes, which is what invalidates prior attestations; and stop if the product ceases to be personal and single-user.

Pin these check locations verbatim:
- `https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan`
- `https://code.claude.com/docs/en/authentication`
- `https://code.claude.com/docs/en/agent-sdk/overview`
- `https://code.claude.com/docs/en/data-usage`

- [ ] **Step 4: Full gate, then stop**

```bash
/Users/frank/.local/bin/uv run --no-sync ruff check .
/Users/frank/.local/bin/uv run --no-sync mypy apps/backend/src packages/protocol/src
/Users/frank/.local/bin/uv run --no-sync pytest -m "not integration" -q
/Users/frank/.local/bin/uv run --no-sync python scripts/ci/check_openapi.py
/Users/frank/.local/bin/uv run --no-sync python scripts/ci/check_repository_policy.py
```

---

## Execution order

Task 1 (table) and Task 2 (settings) touch disjoint files and neither reads the other's output. Task 3 consumes both. All three run in series regardless: implementers in this worktree share one `.venv` and one git index, and running two at once broke both earlier today.
