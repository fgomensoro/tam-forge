# Claude Token Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install two Claude subscription tokens on the host (slot A and slot B) and let the Mac app's Settings > Claude pane choose which one the Claude worker uses, without any token passing through the app or the API.

**Architecture:** A one-row-per-owner table stores the chosen slot. Two owner-only `/ops/claude/slot` routes read and write it. The Claude worker reads it every beat and points `CLAUDE_CODE_OAUTH_TOKEN` at that slot's token, which it captured from its environment on the first beat. The rotation script takes a slot argument and writes that slot's env file. The Mac app adds a segmented slot control to the existing Settings pane.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, pytest; bash; systemd; SwiftUI, XCTest.

**Spec:** `docs/superpowers/specs/2026-09-23-claude-token-slots-design.md`

## Global Constraints

- No endpoint, request body, log line, database row, test fixture or repository file carries a real token. Fixture tokens are exactly `sk-ant-oat01-fixture` and `sk-ant-oat01-fixture-b` (the secret-scan job flags `sk-ant-` followed by 20 or more characters).
- Slot values are exactly `"a"` and `"b"`. No stored choice means `"a"`.
- Slot A: `/etc/tamforge/secrets/claude-oauth.env` holding `CLAUDE_CODE_OAUTH_TOKEN` (unchanged). Slot B: `/etc/tamforge/secrets/claude-oauth-b.env` holding `CLAUDE_CODE_OAUTH_TOKEN_B`. Both `root:tamforge-claude`, mode 0640.
- Alembic revision ids are 32 characters or fewer.
- Every Python command runs as `uv run --no-sync ...` (the worktree's `.venv` is shared; a sync mid-run breaks it).
- Implementers do not commit. The conductor commits after each task's review.
- macOS: run only the unit bundle locally (`-only-testing:TAMForgeTests`). Never run the UI test bundle locally.
- `/ops` routes stay out of OpenAPI (the router already has `include_in_schema=False`).
- User-facing copy is English.

Integration tests use this checkout's own database container:
`TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54337/tamforge_test`

---

### Task 1: Slot table, helpers and migration

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/token_slots.py`
- Create: `apps/backend/alembic/versions/20260923_0037_token_slots.py`
- Create: `apps/backend/tests/unit/agents/test_token_slots.py`
- Create: `apps/backend/tests/integration/agents/test_token_slots_database.py`

**Interfaces:**
- Produces (in `tamforge_backend.agents.token_slots`):
  - `TokenSlot = Literal["a", "b"]`
  - `DEFAULT_SLOT: TokenSlot = "a"`
  - `SLOT_TOKEN_VARS: Mapping[TokenSlot, str]` = `{"a": "CLAUDE_CODE_OAUTH_TOKEN", "b": "CLAUDE_CODE_OAUTH_TOKEN_B"}`
  - `class ClaudeTokenSlot(Base)` on table `claude_token_slots`
  - `async def read_active_slot(session: AsyncSession, *, owner_id: int) -> TokenSlot`
  - `async def choose_slot(session: AsyncSession, *, owner_id: int, slot: TokenSlot) -> None` (commits its own transaction)
  - `def installed_tokens(environ: Mapping[str, str]) -> dict[TokenSlot, str]`
  - `def install_slot_token(slot: TokenSlot, *, tokens: Mapping[TokenSlot, str], environ: MutableMapping[str, str]) -> None`

- [ ] **Step 1: Write the failing unit test**

`apps/backend/tests/unit/agents/test_token_slots.py`:

```python
from __future__ import annotations

from tamforge_backend.agents.token_slots import install_slot_token, installed_tokens


def test_installed_tokens_reads_one_variable_per_slot() -> None:
    environ = {
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture",
        "CLAUDE_CODE_OAUTH_TOKEN_B": "sk-ant-oat01-fixture-b",
        "UNRELATED": "x",
    }
    assert installed_tokens(environ) == {
        "a": "sk-ant-oat01-fixture",
        "b": "sk-ant-oat01-fixture-b",
    }
    assert installed_tokens({}) == {"a": "", "b": ""}


def test_the_chosen_slot_token_becomes_the_one_claude_reads() -> None:
    tokens = {"a": "sk-ant-oat01-fixture", "b": "sk-ant-oat01-fixture-b"}
    environ = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture"}

    install_slot_token("b", tokens=tokens, environ=environ)
    assert environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fixture-b"

    install_slot_token("a", tokens=tokens, environ=environ)
    assert environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fixture"


def test_a_slot_without_a_token_leaves_no_token_to_read() -> None:
    environ = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture"}
    install_slot_token("b", tokens={"a": "sk-ant-oat01-fixture", "b": "  "}, environ=environ)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in environ
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run --no-sync pytest apps/backend/tests/unit/agents/test_token_slots.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tamforge_backend.agents.token_slots'`

- [ ] **Step 3: Write the module**

`apps/backend/src/tamforge_backend/agents/token_slots.py`:

```python
"""Which of the two installed Claude subscription tokens the worker uses.

Both tokens live only on the host, in root-owned env files the Claude worker loads. This
table holds nothing but the owner's choice, "a" or "b", so the API can switch slots
without ever carrying a token.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from datetime import datetime
from types import MappingProxyType
from typing import Literal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now
from .settings import SUBSCRIPTION_TOKEN_VAR

TokenSlot = Literal["a", "b"]
DEFAULT_SLOT: TokenSlot = "a"

# Slot A keeps the variable the host had before slots existed, so the installed
# claude-oauth.env works unchanged; slot B has its own file and variable.
SLOT_TOKEN_VARS: Mapping[TokenSlot, str] = MappingProxyType(
    {"a": SUBSCRIPTION_TOKEN_VAR, "b": "CLAUDE_CODE_OAUTH_TOKEN_B"}
)


class ClaudeTokenSlot(Base):
    __tablename__ = "claude_token_slots"
    __table_args__ = (CheckConstraint("slot IN ('a', 'b')", name="slot_allowed"),)

    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    slot: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


async def read_active_slot(session: AsyncSession, *, owner_id: int) -> TokenSlot:
    stored = await session.scalar(
        select(ClaudeTokenSlot.slot).where(ClaudeTokenSlot.owner_id == owner_id)
    )
    return "b" if stored == "b" else DEFAULT_SLOT


async def choose_slot(session: AsyncSession, *, owner_id: int, slot: TokenSlot) -> None:
    async with session.begin():
        statement = insert(ClaudeTokenSlot).values(
            owner_id=owner_id, slot=slot, updated_at=utc_now()
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[ClaudeTokenSlot.owner_id],
                set_={"slot": statement.excluded.slot, "updated_at": statement.excluded.updated_at},
            )
        )


def installed_tokens(environ: Mapping[str, str]) -> dict[TokenSlot, str]:
    return {slot: environ.get(variable, "") for slot, variable in SLOT_TOKEN_VARS.items()}


def install_slot_token(
    slot: TokenSlot, *, tokens: Mapping[TokenSlot, str], environ: MutableMapping[str, str]
) -> None:
    """Point the one variable every Claude call reads at the chosen slot's token."""
    token = tokens.get(slot, "").strip()
    if token:
        environ[SUBSCRIPTION_TOKEN_VAR] = token
    else:
        environ.pop(SUBSCRIPTION_TOKEN_VAR, None)
```

- [ ] **Step 4: Run the unit test and see it pass**

Run: `uv run --no-sync pytest apps/backend/tests/unit/agents/test_token_slots.py -q`
Expected: 3 passed

- [ ] **Step 5: Write the migration**

`apps/backend/alembic/versions/20260923_0037_token_slots.py`:

```python
"""Claude token slots: which installed subscription token the worker uses."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0037_token_slots"
down_revision = "20260919_0036_shadowing_clips"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claude_token_slots",
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("owner_id", name="pk_claude_token_slots"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_claude_token_slots_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("slot IN ('a', 'b')", name="ck_claude_token_slots_slot_allowed"),
    )


def downgrade() -> None:
    op.drop_table("claude_token_slots")
```

Before writing it, confirm `20260919_0036_shadowing_clips` is still the only head: `uv run --no-sync alembic -c apps/backend/alembic.ini heads`. If another head exists, set `down_revision` to it.

- [ ] **Step 6: Write the failing integration test**

`apps/backend/tests/integration/agents/test_token_slots_database.py`:

```python
"""The slot choice is one row per owner, defaults to A, and refuses anything but a or b."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.integration
def test_the_slot_defaults_to_a_keeps_the_last_choice_and_refuses_others(
    test_database_url: str,
) -> None:
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.token_slots import choose_slot, read_active_slot
    from tamforge_backend.auth.models import Owner

    async def exercise() -> None:
        engine = create_async_engine(
            make_url(test_database_url).set(drivername="postgresql+asyncpg")
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions.begin() as session:
                owner = Owner(github_user_id=102269369, github_login="fgomensoro")
                session.add(owner)
                await session.flush()
                owner_id = owner.id

            async with sessions() as session:
                assert await read_active_slot(session, owner_id=owner_id) == "a"
            async with sessions() as session:
                await choose_slot(session, owner_id=owner_id, slot="b")
            async with sessions() as session:
                await choose_slot(session, owner_id=owner_id, slot="b")
            async with sessions() as session:
                assert await read_active_slot(session, owner_id=owner_id) == "b"
                count = await session.scalar(text("select count(*) from claude_token_slots"))
                assert count == 1
            async with sessions() as session:
                await choose_slot(session, owner_id=owner_id, slot="a")
            async with sessions() as session:
                assert await read_active_slot(session, owner_id=owner_id) == "a"

            with pytest.raises(IntegrityError):
                async with sessions.begin() as session:
                    await session.execute(
                        text("update claude_token_slots set slot = 'c' where owner_id = :id"),
                        {"id": owner_id},
                    )
        finally:
            await engine.dispose()

    asyncio.run(exercise())
```

- [ ] **Step 7: Run it against this checkout's database**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54337/tamforge_test uv run --no-sync pytest -m integration apps/backend/tests/integration/agents/test_token_slots_database.py apps/backend/tests/integration/test_migrations.py -q`
Expected: all passed (the autouse fixture migrates to head, so the new migration runs; `test_migrations` round-trips it).

- [ ] **Step 8: Lint and type-check**

Run: `uv run --no-sync ruff check apps/backend && uv run --no-sync mypy apps/backend/src packages/protocol/src`
Expected: no errors

---

### Task 2: Owner routes to read and switch the slot

**Files:**
- Modify: `apps/backend/src/tamforge_backend/observability/routes.py`
- Modify: `apps/backend/tests/unit/observability/test_routes.py`

**Interfaces:**
- Consumes: `TokenSlot`, `read_active_slot`, `choose_slot` from Task 1.
- Produces: `GET /ops/claude/slot` returns `{"slot": "a" | "b"}`; `PUT /ops/claude/slot` accepts exactly `{"slot": "a" | "b"}` and returns the same body. Both send `Cache-Control: no-store`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/unit/observability/test_routes.py`:

```python
def test_the_owner_reads_and_switches_the_claude_token_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tamforge_backend.auth.dependencies import require_csrf_owner
    from tamforge_backend.database import get_db_session
    from tamforge_backend.observability import routes

    app = create_app(Settings(environment="test", _env_file=None))
    owner = AuthenticatedOwner(
        owner_id=1,
        github_user_id=102269369,
        github_login="private",
        session_id=1,
        csrf_hash=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    app.dependency_overrides[get_authenticated_owner] = lambda: owner
    app.dependency_overrides[require_csrf_owner] = lambda: owner
    app.dependency_overrides[get_db_session] = lambda: object()
    chosen: list[tuple[int, str]] = []

    async def read(session: object, *, owner_id: int) -> str:
        return chosen[-1][1] if chosen else "a"

    async def choose(session: object, *, owner_id: int, slot: str) -> None:
        chosen.append((owner_id, slot))

    monkeypatch.setattr(routes, "read_active_slot", read)
    monkeypatch.setattr(routes, "choose_slot", choose)
    with TestClient(app) as client:
        response = client.get("/ops/claude/slot")
        assert response.json() == {"slot": "a"}
        assert response.headers["cache-control"] == "no-store"

        response = client.put("/ops/claude/slot", json={"slot": "b"})
        assert response.status_code == 200
        assert response.json() == {"slot": "b"}
        assert chosen == [(1, "b")]
        assert client.get("/ops/claude/slot").json() == {"slot": "b"}

        assert client.put("/ops/claude/slot", json={"slot": "c"}).status_code == 422
        assert (
            client.put(
                "/ops/claude/slot", json={"slot": "a", "token": "sk-ant-oat01-fixture"}
            ).status_code
            == 422
        )
        assert chosen == [(1, "b")]
        assert "/ops/claude/slot" not in app.openapi()["paths"]
```

Add `import pytest` at the top of the file if it is not there yet.

In `test_operational_details_require_owner_authentication`, inside the `with TestClient(app) as client:` block, add:

```python
        assert client.get("/ops/claude/slot").status_code == 401
        assert client.put("/ops/claude/slot", json={"slot": "b"}).status_code == 401
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --no-sync pytest apps/backend/tests/unit/observability/test_routes.py -q`
Expected: FAIL (404 on `/ops/claude/slot`, or `AttributeError` on `routes.read_active_slot`)

- [ ] **Step 3: Add the routes**

In `apps/backend/src/tamforge_backend/observability/routes.py`, extend the imports:

```python
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.token_slots import TokenSlot, choose_slot, read_active_slot
from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner
from ..database import DatabaseResources, get_db_session
```

(`get_authenticated_owner` and `DatabaseResources` are already imported; merge rather than duplicate.)

Append at the end of the module:

```python
class TokenSlotChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: TokenSlot


@router.get("/ops/claude/slot")
async def claude_token_slot(
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Which installed subscription token the Claude worker uses; never the token itself."""
    slot = await read_active_slot(session, owner_id=owner.owner_id)
    return JSONResponse({"slot": slot}, headers=NO_STORE)


@router.put("/ops/claude/slot")
async def choose_claude_token_slot(
    choice: TokenSlotChoice,
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Switch slots; the Claude worker picks the choice up on its next beat."""
    await choose_slot(session, owner_id=owner.owner_id, slot=choice.slot)
    return JSONResponse({"slot": choice.slot}, headers=NO_STORE)
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run --no-sync pytest apps/backend/tests/unit/observability/test_routes.py -q`
Expected: all passed

- [ ] **Step 5: Lint, type-check and the OpenAPI gate**

Run: `uv run --no-sync ruff check apps/backend && uv run --no-sync mypy apps/backend/src packages/protocol/src && uv run --no-sync python scripts/ci/check_openapi.py`
Expected: no errors; the OpenAPI check is unchanged because `/ops` routes are excluded.

---

### Task 3: The worker uses the active slot

**Files:**
- Modify: `apps/backend/src/tamforge_backend/workers/claude.py` (`gate_step`, new `_use_slot`, module globals)
- Modify: `apps/backend/tests/unit/workers/test_claude_worker.py`

**Interfaces:**
- Consumes: `TokenSlot`, `DEFAULT_SLOT`, `read_active_slot`, `installed_tokens`, `install_slot_token` from Task 1.
- Produces: `claude._use_slot(slot: TokenSlot, environ: MutableMapping[str, str]) -> None`; module globals `_slot_tokens: dict[TokenSlot, str] | None` and `_active_slot: TokenSlot | None`.

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/unit/workers/test_claude_worker.py`:

```python
def test_switching_slots_swaps_the_token_and_forgets_the_probe_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cached verdict belongs to the old token; the new one is probed on the next beat."""
    from datetime import UTC, datetime

    from tamforge_backend.workers import claude

    verdict = (datetime(2026, 9, 24, 1, 0, tzinfo=UTC), None)
    monkeypatch.setattr(claude, "_slot_tokens", None)
    monkeypatch.setattr(claude, "_active_slot", "a")
    monkeypatch.setattr(claude, "_last_probe", verdict)
    environ = {
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture",
        "CLAUDE_CODE_OAUTH_TOKEN_B": "sk-ant-oat01-fixture-b",
    }

    claude._use_slot("a", environ)
    assert environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fixture"
    assert claude._last_probe == verdict

    claude._use_slot("b", environ)
    assert environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fixture-b"
    assert claude._last_probe is None

    # Slot A's variable was overwritten above; the token captured on the first beat survives.
    claude._use_slot("a", environ)
    assert environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fixture"


def test_a_slot_with_no_token_installed_leaves_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """The settings gate then raises SubscriptionCredentialMissing, which beats as `auth`."""
    from tamforge_backend.workers import claude

    monkeypatch.setattr(claude, "_slot_tokens", None)
    monkeypatch.setattr(claude, "_active_slot", None)
    environ = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture"}

    claude._use_slot("b", environ)

    assert "CLAUDE_CODE_OAUTH_TOKEN" not in environ
```

In `test_the_gate_reads_the_attestation_on_a_fresh_session`, right after `monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)`, add:

```python
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN_B", raising=False)
    monkeypatch.setattr(claude_module, "_slot_tokens", None)
    monkeypatch.setattr(claude_module, "_active_slot", None)
```

and add `from tamforge_backend.workers import claude as claude_module` next to its existing `from tamforge_backend.workers.claude import gate_step` import. That test keeps asserting two sessions: the slot is read on the first session, next to the owner read.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --no-sync pytest apps/backend/tests/unit/workers/test_claude_worker.py -q`
Expected: FAIL with `AttributeError: module 'tamforge_backend.workers.claude' has no attribute '_slot_tokens'`

- [ ] **Step 3: Implement**

In `apps/backend/src/tamforge_backend/workers/claude.py`:

Change `from collections.abc import Mapping` to `from collections.abc import Mapping, MutableMapping`.

Add the import next to the other package imports:

```python
from ..agents.token_slots import (
    DEFAULT_SLOT,
    TokenSlot,
    install_slot_token,
    installed_tokens,
    read_active_slot,
)
```

In `gate_step`, replace the owner read block:

```python
    async with sessions() as session:
        owner_id = await session.scalar(select(Owner.id).order_by(Owner.id).limit(1))
        await session.rollback()
```

with:

```python
    async with sessions() as session:
        owner_id = await session.scalar(select(Owner.id).order_by(Owner.id).limit(1))
        slot = (
            DEFAULT_SLOT
            if owner_id is None
            else await read_active_slot(session, owner_id=owner_id)
        )
        await session.rollback()
    _use_slot(slot, os.environ)
```

Below the `_last_probe` declaration (after `_last_probe: tuple[datetime, str | None] | None = None`), add:

```python
# Both slots' tokens as the worker started with them. Captured once, because installing
# slot B overwrites the variable slot A arrived in.
_slot_tokens: dict[TokenSlot, str] | None = None
_active_slot: TokenSlot | None = None


def _use_slot(slot: TokenSlot, environ: MutableMapping[str, str]) -> None:
    """Install the chosen slot's token; a different slot also drops the probe verdict."""
    global _slot_tokens, _active_slot, _last_probe
    if _slot_tokens is None:
        _slot_tokens = installed_tokens(environ)
    install_slot_token(slot, tokens=_slot_tokens, environ=environ)
    if slot != _active_slot:
        _active_slot = slot
        _last_probe = None
```

`_use_slot` is defined below `gate_step` in the file; that is fine, it is resolved at call time.

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run --no-sync pytest apps/backend/tests/unit/workers/test_claude_worker.py apps/backend/tests/unit/agents -q`
Expected: all passed

- [ ] **Step 5: Lint and type-check**

Run: `uv run --no-sync ruff check apps/backend && uv run --no-sync mypy apps/backend/src packages/protocol/src`
Expected: no errors

---

### Task 4: Rotation script, systemd unit and runbooks

**Files:**
- Modify: `scripts/dev/rotate_claude_token.sh`
- Modify: `Makefile:49-50`
- Modify: `scripts/dev/tests/test_rotate_claude_token.py`
- Modify: `infra/systemd/tamforge-claude-worker.service:21-22`
- Modify: `infra/tests/test_systemd_units.py:97-100`
- Modify: `docs/runbooks/claude-subscription.md` ("Rotating the token" section and the paragraph before it that names the file)
- Modify: `docs/runbooks/host-provisioning.md:46`

**Interfaces:**
- Consumes: table `claude_token_slots(owner_id, slot)` from Task 1 (queried on the host with psql).
- Produces: `scripts/dev/rotate_claude_token.sh [a|b]`; `make rotate-claude-token SLOT=b`. The ssh result line is `<status> <reason>` as today, or `inactive <active slot>` when the rotated slot is not the active one.

- [ ] **Step 1: Write the failing script tests**

In `scripts/dev/tests/test_rotate_claude_token.py`:

Replace `run` with:

```python
def run(env: dict[str, str], token: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        input=f"{token}\n",
        env=env,
        capture_output=True,
        text=True,
    )
```

Add:

```python
def test_slot_b_goes_to_its_own_file_and_variable(
    fake_ssh: tuple[dict[str, str], Path, Path],
) -> None:
    env, argv_log, stdin_log = fake_ssh
    result = run(env, TOKEN, "b")
    assert result.returncode == 0, result.stderr
    assert stdin_log.read_text() == f"CLAUDE_CODE_OAUTH_TOKEN_B={TOKEN}\n"
    remote = argv_log.read_text()
    assert (
        "mv -f /etc/tamforge/secrets/claude-oauth-b.env.new /etc/tamforge/secrets/claude-oauth-b.env"
        in remote
    )
    assert "slot B" in result.stdout


def test_an_unknown_slot_changes_nothing(fake_ssh: tuple[dict[str, str], Path, Path]) -> None:
    env, argv_log, _ = fake_ssh
    result = run(env, TOKEN, "c")
    assert result.returncode == 1
    assert not argv_log.exists()
    assert "Nothing changed" in result.stderr


def test_rotating_the_inactive_slot_does_not_wait_for_its_heartbeat(
    fake_ssh: tuple[dict[str, str], Path, Path],
) -> None:
    env, _, _ = fake_ssh
    result = run({**env, "FAKE_SSH_RESULT": "inactive a"}, TOKEN, "b")
    assert result.returncode == 0, result.stderr
    assert "Slot A is active" in result.stdout
    assert "switch to slot B in Settings > Claude" in result.stdout
```

In `test_the_host_script_installs_0640_before_the_restart_and_reads_only_newer_beats`, change the fake `sudo` to answer the slot query:

```python
    fake_command(
        host_bin / "sudo",
        f'echo "${{@: -1}}" >> {log}\n'
        'case "${@: -1}" in *clock_timestamp*) echo "2026-09-24 01:14:20.88667+00" ;;'
        ' *claude_token_slots*) echo "${FAKE_ACTIVE_SLOT:-a}" ;;'
        ' *) echo "ok none" ;; esac\n',
    )
```

and change the expected log to:

```python
    assert log.read_text().splitlines() == [
        "-rw-------",
        "restart tamforge-claude-worker",
        "claude-oauth.env",
        "select coalesce((select slot from claude_token_slots order by owner_id limit 1), 'a')",
        "select clock_timestamp()",
        "select status || ' ' || reason from worker_heartbeats where worker = 'claude' "
        "and observed_at > '2026-09-24 01:14:20.88667+00'",
    ]
```

Add one more host-side test that reuses the same fakes for slot B while A is active. Copy the setup lines of the test above (secrets dir, `remote` extraction, `host_bin`, `log`, the four `fake_command` calls) into it, running the script with `run(env, TOKEN, "b")` first, then:

```python
    result = subprocess.run(
        ["bash", "-c", remote],
        stdin=stdin_log.open(),
        env={**os.environ, "PATH": f"{host_bin}:{os.environ['PATH']}", "FAKE_ACTIVE_SLOT": "a"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "inactive a\n"
    assert (secrets / "claude-oauth-b.env").read_text() == f"CLAUDE_CODE_OAUTH_TOKEN_B={TOKEN}\n"
    assert "select clock_timestamp()" not in log.read_text()
```

Name it `test_the_host_script_skips_the_heartbeat_wait_for_the_inactive_slot`. Factor the shared fake setup into a helper function in the test module if the copy runs longer than about 15 lines.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --no-sync pytest scripts/dev/tests/test_rotate_claude_token.py -q`
Expected: FAIL (slot B still writes `CLAUDE_CODE_OAUTH_TOKEN=` to `claude-oauth.env`; `c` is accepted)

- [ ] **Step 3: Update the script**

In `scripts/dev/rotate_claude_token.sh`:

Change the header comment's first line to `# Rotates one of the two Claude subscription token slots on the production host.` and add a line `# Usage: rotate_claude_token.sh [a|b]   (make rotate-claude-token SLOT=b); the slot defaults to a.`

Right after `wait_seconds=...`, before the `claude setup-token` block, add:

```bash
slot="${1:-a}"
# Slot A keeps the file and variable the host had before slots existed.
case "$slot" in
  a) file=claude-oauth.env; variable=CLAUDE_CODE_OAUTH_TOKEN ;;
  b) file=claude-oauth-b.env; variable=CLAUDE_CODE_OAUTH_TOKEN_B ;;
  *)
    echo "SLOT must be a or b. Nothing changed." >&2
    exit 1
    ;;
esac
label="$(printf '%s' "$slot" | tr '[:lower:]' '[:upper:]')"
```

Replace the four `claude-oauth.env` lines of the remote heredoc and the restart with:

```bash
cat > /etc/tamforge/secrets/$file.new
chown root:tamforge-claude /etc/tamforge/secrets/$file.new
chmod 0640 /etc/tamforge/secrets/$file.new
mv -f /etc/tamforge/secrets/$file.new /etc/tamforge/secrets/$file
systemctl restart tamforge-claude-worker
# The heartbeat speaks for the active slot only; rotating the other one has nothing to wait for.
active="\$(sudo -u postgres psql -d tamforge -Atc "select coalesce((select slot from claude_token_slots order by owner_id limit 1), 'a')")"
if [ "\$active" != "$slot" ]; then echo "inactive \$active"; exit 0; fi
```

(the `started=...` line and the loop stay as they are, after this).

Change the message before ssh to `echo "Installing the slot $label token and waiting up to $((wait_seconds / 60)) minutes for the Claude worker's first heartbeat."` and the stdin line to:

```bash
if ! result="$(printf '%s=%s\n' "$variable" "$token" | ssh "$host" "$remote")"; then
```

Replace the ending (from `status="${result%% *}"` to the end) with:

```bash
status="${result%% *}"
reason="${result#* }"
next="$(date -u -v+1y +%Y-%m-%d 2>/dev/null || date -u -d '+1 year' +%Y-%m-%d)"
if [ "$status" = "inactive" ]; then
  active_label="$(printf '%s' "$reason" | tr '[:lower:]' '[:upper:]')"
  echo "Token installed in slot $label. Slot $active_label is active; switch to slot $label in Settings > Claude to use it. Rotate again before $next."
  exit 0
fi
if [ "$status" = "ok" ]; then
  echo "Claude worker is ready with the new slot $label token. Rotate again before $next."
  exit 0
fi
echo "Token installed in slot $label, but the Claude worker reports $status ($reason). See docs/runbooks/claude-subscription.md." >&2
exit 1
```

In `Makefile`, change the recipe line under `rotate-claude-token:` to:

```make
	scripts/dev/rotate_claude_token.sh $(SLOT)
```

- [ ] **Step 4: Run the script tests and see them pass**

Run: `uv run --no-sync pytest scripts/dev/tests/test_rotate_claude_token.py -q`
Expected: all passed

- [ ] **Step 5: Systemd unit and its test**

In `infra/tests/test_systemd_units.py`, replace `test_only_the_claude_worker_loads_the_subscription_token` with:

```python
def test_only_the_claude_worker_loads_the_subscription_tokens() -> None:
    for token_file in (
        "-/etc/tamforge/secrets/claude-oauth.env",
        "-/etc/tamforge/secrets/claude-oauth-b.env",
    ):
        loaders = [u.stem for u in UNITS if token_file in parse(u).get("EnvironmentFile", [])]
        assert loaders == ["tamforge-claude-worker"], token_file
```

Run: `uv run --no-sync pytest infra/tests/test_systemd_units.py -q` — Expected: FAIL on `claude-oauth-b.env`.

In `infra/systemd/tamforge-claude-worker.service`, replace:

```ini
# The subscription token; replaced by `make rotate-claude-token`.
EnvironmentFile=-/etc/tamforge/secrets/claude-oauth.env
```

with:

```ini
# The subscription tokens, one file per slot; replaced by `make rotate-claude-token SLOT=a|b`.
# The worker reads which slot is active from the database on every beat.
EnvironmentFile=-/etc/tamforge/secrets/claude-oauth.env
EnvironmentFile=-/etc/tamforge/secrets/claude-oauth-b.env
```

Run: `uv run --no-sync pytest infra/tests/test_systemd_units.py -q` — Expected: all passed.

- [ ] **Step 6: Runbooks**

In `docs/runbooks/claude-subscription.md`, in the paragraph that names `/etc/tamforge/secrets/claude-oauth.env`, say there are two slots: slot A in `claude-oauth.env` holding `CLAUDE_CODE_OAUTH_TOKEN`, slot B in `claude-oauth-b.env` holding `CLAUDE_CODE_OAUTH_TOKEN_B`, same mode and owner, both loaded by the worker unit; the database stores only which slot is active (`claude_token_slots`), never a token.

Rewrite the "Rotating the token" section's first sentence to `Run make rotate-claude-token SLOT=a (or SLOT=b; the default is a) from the repository on the operator's Mac.` and add, after the sentence about waiting for the heartbeat: `When the rotated slot is not the active one, the script restarts the worker and returns without waiting, because the heartbeat reports the active slot only; switch to the new slot in Settings > Claude.`

Replace the paragraph about the Mac app's Settings window with: `The Mac app's Settings window (Cmd+,) has a Claude pane that shows the active slot's worker status, a Slot A / Slot B switch and the rotation command for the chosen slot. Switching sends only the slot name to PUT /ops/claude/slot; the worker picks it up on its next beat and probes the new token. When one subscription runs out of quota, switch to the other slot there. The app never sees a token, and no TAM Forge endpoint accepts one.`

In `docs/runbooks/host-provisioning.md:46`, name both files (`claude-oauth.env` for slot A and `claude-oauth-b.env` for slot B).

- [ ] **Step 7: Full script and infra suites**

Run: `uv run --no-sync pytest infra/tests scripts/dev/tests -q && uv run --no-sync ruff check .`
Expected: all passed, no lint errors

---

### Task 5: Slot switch in Settings > Claude

**Files:**
- Modify: `apps/macos/TAMForge/Features/Settings/ClaudeStatus.swift`
- Modify: `apps/macos/TAMForge/Features/Settings/ClaudeSettingsView.swift`
- Modify: `apps/macos/TAMForgeTests/ClaudeSettingsModelTests.swift`

No new files, so `project.pbxproj` does not change. Invoke the `macos-organic-ui` skill before editing the view: it has the Organic tokens, primitives and the accessibility-identifier contract.

**Interfaces:**
- Consumes: `GET /ops/claude/slot` → `{"slot": "a" | "b"}`; `PUT /ops/claude/slot` with body `{"slot": "a" | "b"}` (Task 2).
- Produces: `enum ClaudeTokenSlot: String, CaseIterable, Codable, Sendable { case a, b }` with `var label: String`; `ClaudeStatusAPI.activeSlot()` and `ClaudeStatusAPI.chooseSlot(_:)`; `ClaudeSettingsModel.slot`, `.switchedSlot`, `.choose(_:)`, `static func rotateCommand(for:)`.

- [ ] **Step 1: Write the failing tests**

In `apps/macos/TAMForgeTests/ClaudeSettingsModelTests.swift`, add inside the test class:

```swift
    func testTheLiveClientReadsAndSwitchesTheSlot() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data(#"{"slot": "b"}"#.utf8)))
        fixture.enqueue(.response(statusCode: 200, body: Data(#"{"slot": "a"}"#.utf8)))
        let api = LiveClaudeStatusAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!, session: fixture.session()
        ))

        let slot = try await api.activeSlot()
        try await api.chooseSlot(.a)

        XCTAssertEqual(slot, .b)
        XCTAssertEqual(fixture.requests.map(\.httpMethod), ["GET", "PUT"])
        XCTAssertEqual(fixture.requests.map { $0.url?.path }, ["/ops/claude/slot", "/ops/claude/slot"])
    }

    func testChoosingASlotSwitchesAndShowsThePendingSwitch() async {
        let api = SlotRecordingAPI()
        let model = ClaudeSettingsModel(api: api)
        await model.refresh()
        XCTAssertEqual(model.slot, .a)

        await model.choose(.b)

        XCTAssertEqual(api.chosen, [.b])
        XCTAssertEqual(model.slot, .b)
        XCTAssertEqual(model.switchedSlot, .b)
        XCTAssertNil(model.state)

        await model.choose(.b)
        XCTAssertEqual(api.chosen, [.b])

        await model.refresh()
        XCTAssertNil(model.switchedSlot)
    }

    func testTheRotationCommandNamesTheSlot() {
        XCTAssertEqual(ClaudeSettingsModel.rotateCommand(for: .a), "make rotate-claude-token SLOT=a")
        XCTAssertEqual(ClaudeSettingsModel.rotateCommand(for: .b), "make rotate-claude-token SLOT=b")
    }
```

Add these two members to `FlakyClaudeStatusAPI`:

```swift
    func activeSlot() async throws -> ClaudeTokenSlot { .a }
    func chooseSlot(_ slot: ClaudeTokenSlot) async throws {}
```

Add at the end of the file:

```swift
@MainActor
private final class SlotRecordingAPI: ClaudeStatusAPI {
    private(set) var chosen: [ClaudeTokenSlot] = []
    private var current: ClaudeTokenSlot = .a

    func claudeState() async throws -> ClaudeTokenState { .quotaSpent }
    func activeSlot() async throws -> ClaudeTokenSlot { current }
    func chooseSlot(_ slot: ClaudeTokenSlot) async throws {
        chosen.append(slot)
        current = slot
    }
}
```

- [ ] **Step 2: Run the unit bundle and see it fail to compile**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests/ClaudeSettingsModelTests test 2>&1 | tail -30`
Expected: build failure, `cannot find type 'ClaudeTokenSlot' in scope`

- [ ] **Step 3: Model and client**

In `apps/macos/TAMForge/Features/Settings/ClaudeStatus.swift`:

Add below the imports:

```swift
/// Which of the two tokens installed on the server the Claude worker uses.
enum ClaudeTokenSlot: String, CaseIterable, Codable, Sendable {
    case a, b

    var label: String { "Slot \(rawValue.uppercased())" }
}
```

Change two `ClaudeTokenState` texts: `.tokenRefused` title to `"Token missing or refused"` and detail to `"Install or rotate this slot's token with the command below."`; `.quotaSpent` detail to `"This slot's quota is used up. Switch to the other slot or wait for the reset."`

Extend the protocol:

```swift
@MainActor
protocol ClaudeStatusAPI {
    func claudeState() async throws -> ClaudeTokenState
    func activeSlot() async throws -> ClaudeTokenSlot
    func chooseSlot(_ slot: ClaudeTokenSlot) async throws
}
```

Add to `LiveClaudeStatusAPI`:

```swift
    private static let slotPath = "/ops/claude/slot"

    func activeSlot() async throws -> ClaudeTokenSlot {
        try await transport.send(.init(method: .get, path: Self.slotPath))
            .decoded(as: SlotChoice.self).slot
    }

    /// Sends only the slot name; the tokens stay on the server.
    func chooseSlot(_ slot: ClaudeTokenSlot) async throws {
        let body = try JSONEncoder().encode(SlotChoice(slot: slot))
        _ = try await transport.send(.init(method: .put, path: Self.slotPath, body: body))
    }
```

Add next to `OperationalStatus`:

```swift
private struct SlotChoice: Codable, Sendable {
    let slot: ClaudeTokenSlot
}
```

Replace `ClaudeSettingsModel` with:

```swift
@MainActor
final class ClaudeSettingsModel: ObservableObject {
    static func rotateCommand(for slot: ClaudeTokenSlot) -> String {
        "make rotate-claude-token SLOT=\(slot.rawValue)"
    }

    @Published private(set) var state: ClaudeTokenState?
    @Published private(set) var slot: ClaudeTokenSlot?
    /// Set right after a switch: the worker picks the new slot up on its next beat, so the
    /// status read at that moment would still describe the previous slot.
    @Published private(set) var switchedSlot: ClaudeTokenSlot?
    @Published private(set) var errorMessage: String?
    @Published private(set) var isLoading = false

    private let api: any ClaudeStatusAPI

    init(api: any ClaudeStatusAPI) {
        self.api = api
    }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            slot = try await api.activeSlot()
            state = try await api.claudeState()
            switchedSlot = nil
            errorMessage = nil
        } catch {
            slot = nil
            state = nil
            switchedSlot = nil
            errorMessage = "Could not read the server status. Try again."
        }
    }

    func choose(_ newSlot: ClaudeTokenSlot) async {
        guard newSlot != slot else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            try await api.chooseSlot(newSlot)
            slot = newSlot
            switchedSlot = newSlot
            state = nil
            errorMessage = nil
        } catch {
            errorMessage = "Could not switch the slot. Try again."
        }
    }
}
```

- [ ] **Step 4: View**

In `apps/macos/TAMForge/Features/Settings/ClaudeSettingsView.swift`:

Update the doc comment to: `/// Settings > Claude: which of the two installed tokens the server's Claude worker uses, whether it is valid, and the command that replaces a slot's token. Tokens never pass through the app.`

In `status`, insert the slot control as the first child of the `VStack`, before the `HStack`:

```swift
            Picker("Token slot", selection: Binding(
                get: { model.slot ?? .a },
                set: { newSlot in Task { await model.choose(newSlot) } }
            )) {
                ForEach(ClaudeTokenSlot.allCases, id: \.self) { slot in
                    Text(slot.label).tag(slot)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .disabled(model.isLoading || model.slot == nil)
            .accessibilityIdentifier("claudeSettingsSlot")
```

If the `macos-organic-ui` skill defines a segmented-control primitive, use it instead of the system `Picker`, keeping the same identifier.

Replace the `if let state = model.state { ... }` detail line with:

```swift
            if let switched = model.switchedSlot {
                Text("The worker switches to \(switched.label) on its next beat. Refresh in a minute to see its status.")
                    .organic(.small)
                    .fixedSize(horizontal: false, vertical: true)
            } else if let state = model.state {
                Text(state.detail).organic(.small).fixedSize(horizontal: false, vertical: true)
            }
```

Change `statusTitle` to:

```swift
    private var statusTitle: String {
        if let switched = model.switchedSlot { return "Switched to \(switched.label)" }
        if let state = model.state { return state.title }
        return model.errorMessage == nil ? "Checking status" : "Status unavailable"
    }
```

In `rotation`, change the explanation to `"To install or replace this slot's token, run this from the repository on your Mac. The token never passes through the app."`, and use `ClaudeSettingsModel.rotateCommand(for: model.slot ?? .a)` in both the `Text` and the `Copy` button (bind it once with a computed `private var rotateCommand: String`).

- [ ] **Step 5: Run the unit bundle and see it pass**

Run: `xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO -only-testing:TAMForgeTests test 2>&1 | tail -30`
Expected: `** TEST SUCCEEDED **`

---

## Execution order

Run tasks one at a time (the worktree's `.venv` and git index are shared): 1, 2, 3, 4, 5. Tasks 2 and 3 need Task 1. Task 4 and Task 5 depend on no other task's code, only on the contracts above.

## Release notes for after merge

1. Deploy the backend (the migration creates `claude_token_slots`; with no row, slot A stays active, so nothing changes until a switch).
2. Reinstall the systemd unit so it loads `claude-oauth-b.env`, then restart `tamforge-claude-worker`.
3. `make rotate-claude-token SLOT=b` with the second subscription's token.
4. Build and install the Mac app DMG.
