# Shadowing Backend Clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Mac a backend home for shadowing clips: an owner-scoped `ShadowingClip` row with its phrases, CRUD under `/api/v1/shadowing-clips`, and a presigned upload and download of the excerpt through the existing object-store port.

**Architecture:** One new package `apps/backend/src/tamforge_backend/shadowing/` shaped like `cards/` (models, schemas, service, routes), one hand-written Alembic revision, router and exception handler registered in `api.py`. The excerpt never passes through the API process: the server signs one `PUT` whose key, length, content type and SHA-256 are pinned, the Mac uploads straight to the store, and a confirm call `stat`s the object before the key is written on the row. Downloads are a short-lived signed `GET`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, PostgreSQL (JSONB), the `storage.ObjectStore` port (`S3ObjectStore` in production, `InMemoryObjectStore` in tests), pytest, ruff, mypy strict.

**Spec:** docs/superpowers/specs/2026-09-18-shadowing-practice-design.md (ticket #363).

## Global Constraints

- Scope is ticket #363 only. No `ShadowingAttempt`, no scoring, no agent roles, no `source_kind = shadowing` on cards, no macOS change (#364 to #369).
- The server never fetches media by URL and never stores excerpt bytes in Postgres; the row stores the object key.
- Every query is owner-scoped (`WHERE owner_id = :owner_id`), as in `cards/` and `practice/`.
- Reuse `storage.ports.ObjectStore`; do not add a second storage abstraction or a new method on the port.
- Alembic revision ids are 32 characters or fewer. This plan uses `20260919_0036_shadowing_clips` (29). Its `down_revision` is `20260918_0035_follow_ups`; re-check `origin/main` for a newer head before starting Task 1 and rebase the number if another session landed `0036`.
- `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py` pins the Alembic head string and must change with the migration.
- `scripts/ci/tests/test_check_openapi.py` pins `FROZEN_OPENAPI_SHA256`; `apps/macos/TAMForge/openapi.yaml` is regenerated with `uv run python scripts/ci/check_openapi.py --write`.
- Pydantic fields that default to a bare `None` break the Swift generator. Optional request fields are `Annotated[T | None, Field(default=None, ...)]` (see `practice/schemas.py`); optional response fields are required-nullable (`T | None`, no default). Response models carry no defaults at all.
- No realistic-looking token, key or hash literal in tests: the secret-scan job reads fixtures. Hashes are computed at runtime or written as `"a" * 64`.
- Unit tests live in `apps/backend/tests/unit/shadowing/` (no `__init__.py`, unique file basenames). Integration tests live in `apps/backend/tests/integration/shadowing/` (with `__init__.py`) and carry `pytest.mark.integration`.
- Integration tests run against a dedicated database through `TEST_DATABASE_URL` on a private port (49152 to 65535), never the shared 54329. Every integration file drops and rebuilds the schema.
- Never run `apps/backend/tests` as one tree (collection collision); always name directories. Never run `tests/integration/foundation/test_month1_workspace.py` locally (locked to the shared MinIO on port 9000).
- `uv` is at `~/.local/bin/uv`, `gh` at `/opt/homebrew/bin/gh`. Run `~/.local/bin/uv sync --all-packages --all-extras --frozen` once before the first test so the environment has the dev extras CI uses.
- TDD: failing test first, watch it fail for the stated reason, minimal code, watch it pass, commit.
- Conventional commits in English, each ending with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- `practice.models` and `cards.models` are not listed in `models/__init__.py::_MODEL_MODULES`; migrations are hand-written. `shadowing.models` follows them and is not added either.

## Commands CI runs

From `.github/workflows/ci.yml` (the only workflow). The backend-relevant jobs:

`backend` job:

```
uv sync --all-packages --all-extras --frozen
uv run ruff check .
uv run python scripts/ci/check_recording_verification.py docs/project/recording-verification-v1.json
uv run mypy apps/backend/src packages/protocol/src
MYPYPATH=apps/backend/src:packages/protocol/src uv run mypy scripts/ci/check_openapi.py scripts/ci/check_repository_policy.py scripts/ci/verify_bootstrap.py scripts/ci/verify_compose.py scripts/dev/seed_foundation_demo.py
uv run python -m scripts.ci.verify_bootstrap
uv run pytest apps/backend/tests/acceptance apps/backend/tests/unit apps/backend/tests/security apps/backend/tests/recordings apps/backend/tests/jobs apps/backend/tests/speech apps/backend/tests/evaluation apps/backend/tests/evals packages/protocol/tests infra/tests scripts/ci/tests scripts/dev/tests scripts/github/tests -m "not integration" -q
```

`backend-integration` job (Postgres service on 54329, MinIO on 9000, CI only):

```
uv sync --all-packages --all-extras --frozen
uv run alembic -c apps/backend/alembic.ini upgrade head
uv run pytest -m "integration and not postgres_integration" apps/backend/tests/integration -q
scripts/run-plan-03-integration.sh apps/backend/tests/integration/agents
```

`e2e` job (CI only, never locally):

```
uv run alembic -c apps/backend/alembic.ini upgrade head
uv run pytest -m integration apps/backend/tests/integration/foundation/test_month1_workspace.py -q
```

`openapi` job: `uv run python scripts/ci/check_openapi.py`

`secret-scan` job: `uv run python scripts/ci/check_repository_policy.py`

`native` and `native-ui` jobs build and test the macOS app with `xcodebuild`; this ticket changes only `apps/macos/TAMForge/openapi.yaml`, which the native build consumes through the pinned generator plugin. They are not run locally.

### Local verify gate (mirrors CI, safe on this Mac)

```
~/.local/bin/uv run ruff check .
~/.local/bin/uv run mypy apps/backend/src packages/protocol/src
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing apps/backend/tests/unit/roadmaps/test_curriculum_schema.py scripts/ci/tests -m "not integration" -q
~/.local/bin/uv run python scripts/ci/check_openapi.py
~/.local/bin/uv run python scripts/ci/check_repository_policy.py
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:<private-port>/tamforge_test ~/.local/bin/uv run pytest -m integration apps/backend/tests/integration/shadowing apps/backend/tests/integration/test_migrations.py -q
```

The issue's own verification line, `uv run pytest apps/backend/tests -q -k shadowing`, collects the whole tree and hits the known collection collision; the two named-directory commands above replace it.

Dedicated database, once per checkout (pick a free port in 49152 to 65535, 54363 below):

```
docker run -d --name tamforge-postgres-54363 -e POSTGRES_DB=tamforge -e POSTGRES_USER=tamforge -e POSTGRES_PASSWORD=tamforge -p 127.0.0.1:54363:5432 pgvector/pgvector:pg16
docker exec tamforge-postgres-54363 createdb -U tamforge tamforge_test
export TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54363/tamforge_test
```

## Design notes the tasks rely on

**Why one presigned PUT plus a confirm is enough.** Recordings do not presign at all: their parts are encrypted, posted to the API, decrypted and written with `put_immutable`, then sealed against a manifest, because a recording is long, produced live, and must survive a crash mid-capture. An excerpt is none of that: it is a finished file of at most two minutes (a few MB of AAC, tens of MB of 720p H.264), far under S3's 5 GB single-PUT limit, and if the upload fails the Mac still has the file and retries. The existing precedent for this shape is `learning/service.py::presign_artifact` and `confirm_artifact`, which call `ObjectStore.presign_put` and then `stat`. `presign_put` already pins `Content-Length`, `Content-Type`, `x-amz-checksum-sha256` and `If-None-Match: *` into the signature, so the store itself refuses a body of another size, type or hash. The confirm step `stat`s the key and re-checks type and size before the row points at it. Unlike `learning`, no command receipt is stored: the key is a pure function of owner, clip and SHA-256, so confirm rebuilds it from the SHA-256 the client sends.

**Bounds.** Content types: `audio/mp4`, `video/mp4`, `video/quicktime` (what `AVAssetExportSession` writes; it cannot write mp3, so an mp3 source is exported as m4a). Size: 1 byte to 100 MiB. Duration: 1 000 to 120 000 ms. Phrases: at most 200, each text 1 to 1000 characters.

**Object key.** `build_object_key(artifact_class="shadowing-excerpt", owner_id=str(owner_id), logical_id=f"clip-{clip_id}", sha256=sha256)`. The key is never sent to the client; responses expose `sha256`, `byte_length`, `content_type`.

**Excerpt is write-once.** The store is immutable and the port has no delete. Confirming the same SHA-256 again is a no-op that returns the clip; a different SHA-256 on a clip that already has an excerpt is a 409. To change the media, delete the clip and create a new one. Deleting a clip removes the row and leaves the object in the store.

**Preparation state.** `pending` (default), `ready`, `failed`. It tracks the server-side `shadowing_prep` annotations of ticket #367; nothing in this ticket moves it. Whether the excerpt is uploaded is read from `excerpt` being null or not.

**Shapes later tickets build on.** `UniqueConstraint(owner_id, id)` lets `ShadowingAttempt` (#366) use a composite owner-scoped foreign key, as `card_reviews` does. `ShadowingAnnotation` (`phrase_index`, `kind` in `slang | idiom | phrase`, `text`, `note`) is the typed element of `annotations` so the Swift contract does not change shape when #367 fills it. `skill_slug` is validated by pattern only (`^[a-z][a-z0-9_]*$`, 1 to 64), exactly as `cards` does; no table in the repo validates it against a catalog.

**Update is a full replace.** `PUT /{clip_id}` takes the same `ShadowingClipCommand` as create, so the contract has no optional request fields at all.

**Routes.**

| Method and path | Auth dependency | Status | Body in | Body out |
| --- | --- | --- | --- | --- |
| `GET /api/v1/shadowing-clips` | `get_authenticated_owner` | 200 | none | `ShadowingClipPage` |
| `POST /api/v1/shadowing-clips` | `require_csrf_owner` | 201 | `ShadowingClipCommand` | `ShadowingClipResponse` |
| `GET /api/v1/shadowing-clips/{clip_id}` | `get_authenticated_owner` | 200 | none | `ShadowingClipResponse` |
| `PUT /api/v1/shadowing-clips/{clip_id}` | `require_csrf_owner` | 200 | `ShadowingClipCommand` | `ShadowingClipResponse` |
| `DELETE /api/v1/shadowing-clips/{clip_id}` | `require_csrf_owner` | 204 | none | none |
| `POST /api/v1/shadowing-clips/{clip_id}/excerpt/upload` | `require_csrf_owner` | 200 | `ExcerptUploadCommand` | `ExcerptUploadResponse` |
| `POST /api/v1/shadowing-clips/{clip_id}/excerpt/confirm` | `require_csrf_owner` | 200 | `ExcerptConfirmCommand` | `ShadowingClipResponse` |
| `GET /api/v1/shadowing-clips/{clip_id}/excerpt/download` | `get_authenticated_owner` | 200 | none | `ExcerptDownloadResponse` |

Problems: `ShadowingNotFound` 404 `shadowing_clip_not_found`, `ShadowingInvalid` 422 `invalid_shadowing_command`, `ShadowingConflict` 409 `shadowing_conflict`, `ShadowingUnavailable` 503 `shadowing_unavailable`, anything else under `ShadowingError` 500 `shadowing_error`.

---

## Task 1: `ShadowingClip` model, migration and head pin

**Files**
- Create: `apps/backend/src/tamforge_backend/shadowing/__init__.py`
- Create: `apps/backend/src/tamforge_backend/shadowing/models.py`
- Create: `apps/backend/alembic/versions/20260919_0036_shadowing_clips.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py` (line 1028, the head string)
- Test: `apps/backend/tests/unit/shadowing/test_shadowing_clip_model.py`

**Interfaces**
- Consumes: `tamforge_backend.models.base.Base`, `utc_now`; table `owners`.
- Produces: `tamforge_backend.shadowing.models.ShadowingClip` (table `shadowing_clips`), constants `SHADOWING_FORMATS: tuple[str, ...] = ("solo", "dialogue")`, `PREPARATION_STATES: tuple[str, ...] = ("pending", "ready", "failed")`, `EXCERPT_CONTENT_TYPES: tuple[str, ...] = ("audio/mp4", "video/mp4", "video/quicktime")`, `MAX_CLIP_DURATION_MS = 120_000`, `MAX_EXCERPT_BYTES = 100 * 1024 * 1024`. Alembic revision `20260919_0036_shadowing_clips`.

**Independent of:** Task 2.

- [ ] **Step 1: write the failing test.** Create `apps/backend/tests/unit/shadowing/test_shadowing_clip_model.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path

MIGRATION = Path("apps/backend/alembic/versions/20260919_0036_shadowing_clips.py")


def test_clip_table_has_the_agreed_columns_and_owner_scope() -> None:
    from tamforge_backend.shadowing.models import (
        EXCERPT_CONTENT_TYPES,
        PREPARATION_STATES,
        SHADOWING_FORMATS,
        ShadowingClip,
    )

    table = ShadowingClip.__table__
    assert table.name == "shadowing_clips"
    assert {column.name for column in table.columns} == {
        "id",
        "owner_id",
        "title",
        "format",
        "skill_slug",
        "source_note",
        "license_note",
        "duration_ms",
        "phrases",
        "annotations",
        "preparation_state",
        "excerpt_object_key",
        "excerpt_content_type",
        "excerpt_byte_length",
        "created_at",
        "updated_at",
    }
    assert [key.target_fullname for key in table.c.owner_id.foreign_keys] == ["owners.id"]
    assert table.c.excerpt_object_key.nullable
    assert not table.c.phrases.nullable and not table.c.annotations.nullable
    assert SHADOWING_FORMATS == ("solo", "dialogue")
    assert PREPARATION_STATES == ("pending", "ready", "failed")
    assert EXCERPT_CONTENT_TYPES == ("audio/mp4", "video/mp4", "video/quicktime")


def test_migration_id_fits_alembic_version_and_follows_the_current_head() -> None:
    spec = importlib.util.spec_from_file_location("shadowing_clips_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260919_0036_shadowing_clips"
    assert len(module.revision) <= 32
    assert module.down_revision == "20260918_0035_follow_ups"
```

- [ ] **Step 2: run it and see it fail.**

```
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing/test_shadowing_clip_model.py -q
```

Expected: 2 failed. The first with `ModuleNotFoundError: No module named 'tamforge_backend.shadowing'`, the second with `FileNotFoundError` on the migration path.

- [ ] **Step 3: create the package marker.** `apps/backend/src/tamforge_backend/shadowing/__init__.py`:

```python
"""Shadowing practice: clips of native audio, split into phrases, drilled by ear."""
```

- [ ] **Step 4: write the model.** `apps/backend/src/tamforge_backend/shadowing/models.py`:

```python
"""One shadowing clip: a short excerpt in the object store and the phrases to loop over."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now

SHADOWING_FORMATS = ("solo", "dialogue")
PREPARATION_STATES = ("pending", "ready", "failed")
EXCERPT_CONTENT_TYPES = ("audio/mp4", "video/mp4", "video/quicktime")
MAX_CLIP_DURATION_MS = 120_000
MAX_EXCERPT_BYTES = 100 * 1024 * 1024


class ShadowingClip(Base):
    """The excerpt lives in the object store; this row holds its key, never its bytes.

    The three excerpt columns are set together by the confirm step, once the uploaded
    object has been seen in the store. `annotations` is filled by clip preparation.
    """

    __tablename__ = "shadowing_clips"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_shadowing_clips_owner_id_id"),
        UniqueConstraint("excerpt_object_key", name="uq_shadowing_clips_excerpt_object_key"),
        CheckConstraint("format IN ('solo', 'dialogue')", name="format_allowed"),
        CheckConstraint(
            "preparation_state IN ('pending', 'ready', 'failed')", name="preparation_state_allowed"
        ),
        CheckConstraint("btrim(title) <> '' AND octet_length(title) <= 800", name="title_bounded"),
        CheckConstraint(
            "octet_length(source_note) <= 2000 AND octet_length(license_note) <= 2000",
            name="notes_bounded",
        ),
        CheckConstraint("duration_ms BETWEEN 1000 AND 120000", name="duration_bounded"),
        CheckConstraint("jsonb_typeof(phrases) = 'array'", name="phrases_array"),
        CheckConstraint("jsonb_typeof(annotations) = 'array'", name="annotations_array"),
        CheckConstraint(
            "(excerpt_object_key IS NULL) = (excerpt_content_type IS NULL) "
            "AND (excerpt_object_key IS NULL) = (excerpt_byte_length IS NULL)",
            name="excerpt_complete_or_absent",
        ),
        CheckConstraint(
            "excerpt_content_type IS NULL "
            "OR excerpt_content_type IN ('audio/mp4', 'video/mp4', 'video/quicktime')",
            name="excerpt_content_type_allowed",
        ),
        CheckConstraint(
            "excerpt_byte_length IS NULL OR excerpt_byte_length BETWEEN 1 AND 104857600",
            name="excerpt_byte_length_bounded",
        ),
        Index("ix_shadowing_clips_owner_created", "owner_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_shadowing_clips_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    skill_slug: Mapped[str] = mapped_column(Text, nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    license_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    phrases: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    annotations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    preparation_state: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    excerpt_object_key: Mapped[str | None] = mapped_column(Text)
    excerpt_content_type: Mapped[str | None] = mapped_column(Text)
    excerpt_byte_length: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = [
    "EXCERPT_CONTENT_TYPES",
    "MAX_CLIP_DURATION_MS",
    "MAX_EXCERPT_BYTES",
    "PREPARATION_STATES",
    "SHADOWING_FORMATS",
    "ShadowingClip",
]
```

- [ ] **Step 5: write the migration.** `apps/backend/alembic/versions/20260919_0036_shadowing_clips.py`:

```python
"""Shadowing clips: a short excerpt in the object store and its phrases."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260919_0036_shadowing_clips"
down_revision = "20260918_0035_follow_ups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadowing_clips",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("skill_slug", sa.Text(), nullable=False),
        sa.Column("source_note", sa.Text(), server_default="", nullable=False),
        sa.Column("license_note", sa.Text(), server_default="", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "phrases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "annotations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("preparation_state", sa.Text(), server_default="pending", nullable=False),
        sa.Column("excerpt_object_key", sa.Text(), nullable=True),
        sa.Column("excerpt_content_type", sa.Text(), nullable=True),
        sa.Column("excerpt_byte_length", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shadowing_clips"),
        sa.UniqueConstraint("owner_id", "id", name="uq_shadowing_clips_owner_id_id"),
        sa.UniqueConstraint("excerpt_object_key", name="uq_shadowing_clips_excerpt_object_key"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_shadowing_clips_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("format IN ('solo', 'dialogue')", name="format_allowed"),
        sa.CheckConstraint(
            "preparation_state IN ('pending', 'ready', 'failed')", name="preparation_state_allowed"
        ),
        sa.CheckConstraint(
            "btrim(title) <> '' AND octet_length(title) <= 800", name="title_bounded"
        ),
        sa.CheckConstraint(
            "octet_length(source_note) <= 2000 AND octet_length(license_note) <= 2000",
            name="notes_bounded",
        ),
        sa.CheckConstraint("duration_ms BETWEEN 1000 AND 120000", name="duration_bounded"),
        sa.CheckConstraint("jsonb_typeof(phrases) = 'array'", name="phrases_array"),
        sa.CheckConstraint("jsonb_typeof(annotations) = 'array'", name="annotations_array"),
        sa.CheckConstraint(
            "(excerpt_object_key IS NULL) = (excerpt_content_type IS NULL) "
            "AND (excerpt_object_key IS NULL) = (excerpt_byte_length IS NULL)",
            name="excerpt_complete_or_absent",
        ),
        sa.CheckConstraint(
            "excerpt_content_type IS NULL "
            "OR excerpt_content_type IN ('audio/mp4', 'video/mp4', 'video/quicktime')",
            name="excerpt_content_type_allowed",
        ),
        sa.CheckConstraint(
            "excerpt_byte_length IS NULL OR excerpt_byte_length BETWEEN 1 AND 104857600",
            name="excerpt_byte_length_bounded",
        ),
    )
    op.create_index(
        "ix_shadowing_clips_owner_created",
        "shadowing_clips",
        ["owner_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shadowing_clips_owner_created", table_name="shadowing_clips")
    op.drop_table("shadowing_clips")
```

- [ ] **Step 6: move the head pin.** In `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py`, inside `test_alembic_has_exactly_one_linear_head`, replace

```python
    assert result.stdout.strip() == "20260918_0035_follow_ups (head)"
```

with

```python
    assert result.stdout.strip() == "20260919_0036_shadowing_clips (head)"
```

- [ ] **Step 7: run and expect pass.**

```
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing/test_shadowing_clip_model.py "apps/backend/tests/unit/roadmaps/test_curriculum_schema.py::test_alembic_has_exactly_one_linear_head" -q
```

Expected: 3 passed. (`alembic heads` reads the scripts only; it touches no database.)

- [ ] **Step 8: lint and types.**

```
~/.local/bin/uv run ruff check apps/backend/src/tamforge_backend/shadowing apps/backend/alembic/versions/20260919_0036_shadowing_clips.py apps/backend/tests/unit/shadowing
~/.local/bin/uv run mypy apps/backend/src packages/protocol/src
```

Expected: both clean.

- [ ] **Step 9: commit.**

```
git add apps/backend/src/tamforge_backend/shadowing/__init__.py apps/backend/src/tamforge_backend/shadowing/models.py apps/backend/alembic/versions/20260919_0036_shadowing_clips.py apps/backend/tests/unit/shadowing/test_shadowing_clip_model.py apps/backend/tests/unit/roadmaps/test_curriculum_schema.py
git commit -m "feat(shadowing): add the shadowing clip table" -m "An owner-scoped clip row with its phrases and annotations as JSONB and the object-store key of its excerpt. The three excerpt columns are set together or not at all." -m "Refs #363" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 2: Wire schemas and phrase validation

**Files**
- Create: `apps/backend/src/tamforge_backend/shadowing/schemas.py`
- Test: `apps/backend/tests/unit/shadowing/test_shadowing_schemas.py`

**Interfaces**
- Consumes: `tamforge_backend.learning.schemas.PresignedUploadResponse` (`url: str`, `method: Literal["PUT"]`, `headers: dict[str, str]`, `expires_seconds: int`), reused so the Swift contract keeps one upload type.
- Produces (all Pydantic, `extra="forbid"`, frozen):
  - `ShadowingFormat = Literal["solo", "dialogue"]`
  - `PreparationState = Literal["pending", "ready", "failed"]`
  - `ExcerptContentType = Literal["audio/mp4", "video/mp4", "video/quicktime"]`
  - `ShadowingPhrase(index: int, start_ms: int, end_ms: int, text: str, enabled: bool)`
  - `ShadowingAnnotation(phrase_index: int, kind: Literal["slang", "idiom", "phrase"], text: str, note: str)`
  - `ShadowingClipCommand(title: str, format: ShadowingFormat, skill_slug: str, source_note: str = "", license_note: str = "", duration_ms: int, phrases: tuple[ShadowingPhrase, ...] = ())`
  - `ShadowingExcerptResponse(sha256: str, byte_length: int, content_type: ExcerptContentType)`
  - `ShadowingClipResponse(id, title, format, skill_slug, source_note, license_note, duration_ms, phrases, annotations, preparation_state, excerpt: ShadowingExcerptResponse | None, created_at, updated_at)`
  - `ShadowingClipPage(items: tuple[ShadowingClipResponse, ...])`
  - `ExcerptUploadCommand(sha256: str, byte_length: int, content_type: ExcerptContentType)`
  - `ExcerptUploadResponse(upload: PresignedUploadResponse)`
  - `ExcerptConfirmCommand(sha256: str)`
  - `ExcerptDownloadResponse(url: str, expires_seconds: int, sha256: str, byte_length: int, content_type: ExcerptContentType)`
  - Constants `MAX_PHRASES = 200`, and re-exported `MAX_CLIP_DURATION_MS`, `MAX_EXCERPT_BYTES`.

**Independent of:** Task 1 for the tests; the module imports two integer constants from `shadowing/models.py`, so Task 1 Step 3 and Step 4 must exist on disk. If the two tasks run in parallel worktrees, merge Task 1 first.

- [ ] **Step 1: write the failing test.** Create `apps/backend/tests/unit/shadowing/test_shadowing_schemas.py`:

```python
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError


def _phrase(index: int, start_ms: int, end_ms: int, text: str = "Thanks for joining.") -> dict[str, Any]:
    return {"index": index, "start_ms": start_ms, "end_ms": end_ms, "text": text, "enabled": True}


def _command(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "QBR opening",
        "format": "solo",
        "skill_slug": "english_fluency",
        "source_note": "Recorded talk, minute 3",
        "license_note": "CC BY 4.0",
        "duration_ms": 45_000,
        "phrases": [_phrase(0, 0, 2_000), _phrase(1, 2_000, 4_500)],
    }
    body.update(overrides)
    return body


def test_a_well_formed_clip_is_accepted_and_notes_default_to_empty() -> None:
    from tamforge_backend.shadowing.schemas import ShadowingClipCommand

    command = ShadowingClipCommand.model_validate(_command())
    assert [phrase.index for phrase in command.phrases] == [0, 1]
    assert command.phrases[1].start_ms == 2_000

    bare = _command()
    del bare["source_note"], bare["license_note"], bare["phrases"]
    minimal = ShadowingClipCommand.model_validate(bare)
    assert minimal.source_note == "" and minimal.license_note == "" and minimal.phrases == ()


@pytest.mark.parametrize(
    ("phrases", "reason"),
    [
        ([_phrase(1, 0, 2_000)], "count up from zero"),
        ([_phrase(0, 0, 2_000), _phrase(2, 2_000, 3_000)], "count up from zero"),
        ([_phrase(0, 2_000, 2_000)], "end after it starts"),
        ([_phrase(0, 3_000, 2_000)], "end after it starts"),
        ([_phrase(0, 0, 2_000), _phrase(1, 1_999, 3_000)], "must not overlap"),
        ([_phrase(0, 5_000, 6_000), _phrase(1, 0, 1_000)], "must not overlap"),
        ([_phrase(0, 44_000, 45_001)], "inside the clip"),
    ],
)
def test_phrases_are_ordered_non_overlapping_and_inside_the_clip(
    phrases: list[dict[str, Any]], reason: str
) -> None:
    from tamforge_backend.shadowing.schemas import ShadowingClipCommand

    with pytest.raises(ValidationError) as error:
        ShadowingClipCommand.model_validate(_command(phrases=phrases))
    assert reason in str(error.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"format": "trio"},
        {"skill_slug": "English Fluency"},
        {"skill_slug": ""},
        {"duration_ms": 999},
        {"duration_ms": 120_001},
        {"source_note": "x" * 501},
        {"license_note": "x" * 501},
        {"phrases": [_phrase(0, 0, 2_000, text="")]},
        {"unknown": 1},
    ],
)
def test_out_of_bounds_clip_fields_are_refused(overrides: dict[str, Any]) -> None:
    from tamforge_backend.shadowing.schemas import ShadowingClipCommand

    with pytest.raises(ValidationError):
        ShadowingClipCommand.model_validate(_command(**overrides))


def test_more_than_two_hundred_phrases_are_refused() -> None:
    from tamforge_backend.shadowing.schemas import MAX_PHRASES, ShadowingClipCommand

    phrases = [_phrase(i, i * 100, i * 100 + 100) for i in range(MAX_PHRASES + 1)]
    with pytest.raises(ValidationError):
        ShadowingClipCommand.model_validate(_command(duration_ms=120_000, phrases=phrases))


def test_excerpt_upload_bounds_type_size_and_hash() -> None:
    from tamforge_backend.shadowing.schemas import MAX_EXCERPT_BYTES, ExcerptUploadCommand

    digest = "a" * 64
    accepted = ExcerptUploadCommand(sha256=digest, byte_length=1_024, content_type="audio/mp4")
    assert accepted.content_type == "audio/mp4"
    for body in (
        {"sha256": digest, "byte_length": 0, "content_type": "audio/mp4"},
        {"sha256": digest, "byte_length": MAX_EXCERPT_BYTES + 1, "content_type": "audio/mp4"},
        {"sha256": digest, "byte_length": 1_024, "content_type": "audio/mpeg"},
        {"sha256": digest, "byte_length": 1_024, "content_type": "application/octet-stream"},
        {"sha256": "A" * 64, "byte_length": 1_024, "content_type": "video/mp4"},
        {"sha256": "a" * 63, "byte_length": 1_024, "content_type": "video/mp4"},
    ):
        with pytest.raises(ValidationError):
            ExcerptUploadCommand.model_validate(body)


def test_no_field_reaches_the_swift_generator_with_a_bare_none_default() -> None:
    from tamforge_backend.shadowing import schemas

    for name in schemas.__all__:
        model = getattr(schemas, name)
        if not hasattr(model, "model_fields"):
            continue
        for field_name, field in model.model_fields.items():
            assert field.default is not None, f"{name}.{field_name} defaults to None"
    assert schemas.ShadowingClipResponse.model_fields["excerpt"].is_required()
```

- [ ] **Step 2: run it and see it fail.**

```
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing/test_shadowing_schemas.py -q
```

Expected: every test fails with `ModuleNotFoundError: No module named 'tamforge_backend.shadowing.schemas'`.

- [ ] **Step 3: write the schemas.** `apps/backend/src/tamforge_backend/shadowing/schemas.py`:

```python
"""Wire shapes of shadowing clips and of the excerpt upload and download."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..learning.schemas import PresignedUploadResponse
from .models import MAX_CLIP_DURATION_MS, MAX_EXCERPT_BYTES

ShadowingFormat = Literal["solo", "dialogue"]
PreparationState = Literal["pending", "ready", "failed"]
ExcerptContentType = Literal["audio/mp4", "video/mp4", "video/quicktime"]
MAX_PHRASES = 200

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ShadowingPhrase(StrictModel):
    """One loopable stretch of the excerpt. `enabled` is how a dialogue is followed by hand:
    the learner switches off the phrases of the speaker they are not shadowing."""

    index: Annotated[int, Field(ge=0, lt=MAX_PHRASES)]
    start_ms: Annotated[int, Field(ge=0, le=MAX_CLIP_DURATION_MS)]
    end_ms: Annotated[int, Field(ge=1, le=MAX_CLIP_DURATION_MS)]
    text: Annotated[str, Field(min_length=1, max_length=1000)]
    enabled: bool


class ShadowingAnnotation(StrictModel):
    """Something in the clip worth stealing, written by clip preparation."""

    phrase_index: Annotated[int, Field(ge=0, lt=MAX_PHRASES)]
    kind: Literal["slang", "idiom", "phrase"]
    text: Annotated[str, Field(min_length=1, max_length=500)]
    note: Annotated[str, Field(min_length=1, max_length=500)]


class ShadowingClipCommand(StrictModel):
    """Everything the learner decides about a clip. Create and replace take the same body."""

    title: Annotated[str, Field(min_length=1, max_length=200)]
    format: ShadowingFormat
    skill_slug: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    source_note: Annotated[str, Field(default="", max_length=500)]
    license_note: Annotated[str, Field(default="", max_length=500)]
    duration_ms: Annotated[int, Field(ge=1000, le=MAX_CLIP_DURATION_MS)]
    phrases: Annotated[tuple[ShadowingPhrase, ...], Field(default=(), max_length=MAX_PHRASES)]

    @model_validator(mode="after")
    def _phrases_fit_the_clip(self) -> ShadowingClipCommand:
        if not self.title.strip():
            raise ValueError("the title cannot be blank")
        previous_end = 0
        for position, phrase in enumerate(self.phrases):
            if phrase.index != position:
                raise ValueError("phrase indexes must count up from zero")
            if phrase.end_ms <= phrase.start_ms:
                raise ValueError("a phrase must end after it starts")
            if phrase.start_ms < previous_end:
                raise ValueError("phrases must be ordered and must not overlap")
            if phrase.end_ms > self.duration_ms:
                raise ValueError("every phrase must be inside the clip")
            previous_end = phrase.end_ms
        return self


class ShadowingExcerptResponse(StrictModel):
    sha256: str
    byte_length: int
    content_type: ExcerptContentType


class ShadowingClipResponse(StrictModel):
    id: int
    title: str
    format: ShadowingFormat
    skill_slug: str
    source_note: str
    license_note: str
    duration_ms: int
    phrases: tuple[ShadowingPhrase, ...]
    annotations: tuple[ShadowingAnnotation, ...]
    preparation_state: PreparationState
    excerpt: ShadowingExcerptResponse | None
    created_at: datetime
    updated_at: datetime


class ShadowingClipPage(StrictModel):
    items: tuple[ShadowingClipResponse, ...]


class ExcerptUploadCommand(StrictModel):
    """What the Mac is about to upload. The signed request accepts exactly this and no other."""

    sha256: Sha256
    byte_length: Annotated[int, Field(ge=1, le=MAX_EXCERPT_BYTES)]
    content_type: ExcerptContentType


class ExcerptUploadResponse(StrictModel):
    upload: PresignedUploadResponse


class ExcerptConfirmCommand(StrictModel):
    sha256: Sha256


class ExcerptDownloadResponse(StrictModel):
    url: str
    expires_seconds: int
    sha256: str
    byte_length: int
    content_type: ExcerptContentType


__all__ = [
    "MAX_CLIP_DURATION_MS",
    "MAX_EXCERPT_BYTES",
    "MAX_PHRASES",
    "ExcerptConfirmCommand",
    "ExcerptContentType",
    "ExcerptDownloadResponse",
    "ExcerptUploadCommand",
    "ExcerptUploadResponse",
    "PreparationState",
    "ShadowingAnnotation",
    "ShadowingClipCommand",
    "ShadowingClipPage",
    "ShadowingClipResponse",
    "ShadowingExcerptResponse",
    "ShadowingFormat",
    "ShadowingPhrase",
]
```

- [ ] **Step 4: run and expect pass.**

```
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing/test_shadowing_schemas.py -q
```

Expected: all passed (23 cases).

- [ ] **Step 5: lint and types.**

```
~/.local/bin/uv run ruff check apps/backend/src/tamforge_backend/shadowing apps/backend/tests/unit/shadowing
~/.local/bin/uv run mypy apps/backend/src packages/protocol/src
```

Expected: both clean. If ruff flags the `_phrase` helper signature for length, break it after the opening parenthesis; the line is 99 characters.

- [ ] **Step 6: commit.**

```
git add apps/backend/src/tamforge_backend/shadowing/schemas.py apps/backend/tests/unit/shadowing/test_shadowing_schemas.py
git commit -m "feat(shadowing): wire shapes for clips and the excerpt upload" -m "Phrases are refused unless their indexes count up from zero and they are ordered, non-overlapping and inside the clip duration. The excerpt upload is bounded to three content types and 100 MiB. No field defaults to a bare None." -m "Refs #363" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 3: Owner-scoped clip service (create, list, get, replace, delete)

**Files**
- Create: `apps/backend/src/tamforge_backend/shadowing/service.py`
- Create: `apps/backend/tests/integration/shadowing/__init__.py` (empty)
- Test: `apps/backend/tests/integration/shadowing/test_shadowing_clips.py`

**Interfaces**
- Consumes: `ShadowingClip` (Task 1); `ShadowingClipCommand`, `ShadowingClipResponse`, `ShadowingClipPage`, `ShadowingPhrase`, `ShadowingAnnotation`, `ShadowingExcerptResponse` (Task 2); `tamforge_backend.database.transaction_scope`; `tamforge_backend.storage.ports.ObjectStore`.
- Produces:
  - `class ShadowingError(Exception)`, `ShadowingNotFound`, `ShadowingInvalid`, `ShadowingConflict`, `ShadowingUnavailable` (all subclasses of `ShadowingError`).
  - `class ShadowingClipService` with
    - `__init__(self, session: AsyncSession, object_store: ObjectStore, *, clock: Callable[[], datetime] = utc_now) -> None`
    - `async def create(self, *, owner_id: int, command: ShadowingClipCommand) -> ShadowingClipResponse`
    - `async def list(self, *, owner_id: int) -> ShadowingClipPage` (newest first)
    - `async def get(self, *, owner_id: int, clip_id: int) -> ShadowingClipResponse`
    - `async def replace(self, *, owner_id: int, clip_id: int, command: ShadowingClipCommand) -> ShadowingClipResponse`
    - `async def delete(self, *, owner_id: int, clip_id: int) -> None`

**Independent of:** none (needs Tasks 1 and 2).

Every method, reads included, runs inside `transaction_scope` and builds its response before the scope closes. `cards` rolls back after reads instead; a rollback expires the loaded rows, and touching one afterwards on an async session raises `MissingGreenlet`. One pattern for all eight methods avoids that trap.

- [ ] **Step 1: write the failing test.** Create the empty file `apps/backend/tests/integration/shadowing/__init__.py`, then `apps/backend/tests/integration/shadowing/test_shadowing_clips.py`:

```python
"""Shadowing clips on Postgres: owner-scoped CRUD and the excerpt upload round trip."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
LATER = datetime(2026, 9, 19, 13, tzinfo=UTC)


@contextmanager
def _two_owners(test_database_url: str) -> Iterator[tuple[int, int]]:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from tamforge_backend.database import database_url_to_sync

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
            other_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (7, 'someone') RETURNING id"
                )
            ).scalar_one()
        yield owner_id, other_id
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()


def _run(test_database_url: str, exercise: Callable[[Any], Awaitable[None]]) -> None:
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def main() -> None:
        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
        engine = create_async_engine(async_url)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            await exercise(factory)
        finally:
            await engine.dispose()

    asyncio.run(main())


def _command(title: str = "QBR opening") -> Any:
    from tamforge_backend.shadowing.schemas import ShadowingClipCommand, ShadowingPhrase

    return ShadowingClipCommand(
        title=title,
        format="dialogue",
        skill_slug="english_fluency",
        source_note="Recorded talk, minute 3",
        license_note="CC BY 4.0",
        duration_ms=45_000,
        phrases=(
            ShadowingPhrase(index=0, start_ms=0, end_ms=2_000, text="Thanks for joining.", enabled=True),
            ShadowingPhrase(index=1, start_ms=2_000, end_ms=4_500, text="Let's dive in.", enabled=False),
        ),
    )


def test_clips_are_created_listed_replaced_and_deleted_per_owner(test_database_url: str) -> None:
    from tamforge_backend.shadowing.service import ShadowingClipService, ShadowingNotFound
    from tamforge_backend.storage.fake import InMemoryObjectStore

    with _two_owners(test_database_url) as (owner_id, other_id):

        async def exercise(factory: Any) -> None:
            store = InMemoryObjectStore()
            async with factory() as session:
                service = ShadowingClipService(session, store, clock=lambda: NOW)
                created = await service.create(owner_id=owner_id, command=_command())
            assert created.title == "QBR opening" and created.format == "dialogue"
            assert created.preparation_state == "pending"
            assert created.annotations == () and created.excerpt is None
            assert [phrase.enabled for phrase in created.phrases] == [True, False]
            assert created.created_at == NOW and created.updated_at == NOW

            async with factory() as session:
                service = ShadowingClipService(session, store, clock=lambda: LATER)
                second = await service.create(owner_id=owner_id, command=_command("Renewal call"))
                foreign = await service.create(owner_id=other_id, command=_command("Not yours"))
                page = await service.list(owner_id=owner_id)
                assert [item.id for item in page.items] == [second.id, created.id]
                assert (await service.get(owner_id=owner_id, clip_id=created.id)) == created

                replaced = await service.replace(
                    owner_id=owner_id, clip_id=created.id, command=_command("QBR opening, take 2")
                )
                assert replaced.title == "QBR opening, take 2"
                assert replaced.created_at == NOW and replaced.updated_at == LATER

                for call in (
                    service.get(owner_id=owner_id, clip_id=foreign.id),
                    service.replace(owner_id=owner_id, clip_id=foreign.id, command=_command()),
                    service.delete(owner_id=owner_id, clip_id=foreign.id),
                    service.get(owner_id=owner_id, clip_id=999_999),
                ):
                    with pytest.raises(ShadowingNotFound):
                        await call

                await service.delete(owner_id=owner_id, clip_id=created.id)
                with pytest.raises(ShadowingNotFound):
                    await service.get(owner_id=owner_id, clip_id=created.id)
                assert [item.id for item in (await service.list(owner_id=owner_id)).items] == [
                    second.id
                ]
                assert len((await service.list(owner_id=other_id)).items) == 1

        _run(test_database_url, exercise)
```

- [ ] **Step 2: run it and see it fail.** With the dedicated database from "Commands CI runs" exported as `TEST_DATABASE_URL`:

```
~/.local/bin/uv run pytest -m integration apps/backend/tests/integration/shadowing -q
```

Expected: 1 failed with `ModuleNotFoundError: No module named 'tamforge_backend.shadowing.service'`. (Without `TEST_DATABASE_URL` the test is skipped, which is not a pass: export it.)

- [ ] **Step 3: write the service.** `apps/backend/src/tamforge_backend/shadowing/service.py`:

```python
"""Shadowing clips: owner-scoped rows whose excerpt lives in the object store."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..models.base import utc_now
from ..storage.ports import ObjectStore
from .models import ShadowingClip
from .schemas import (
    ShadowingAnnotation,
    ShadowingClipCommand,
    ShadowingClipPage,
    ShadowingClipResponse,
    ShadowingExcerptResponse,
    ShadowingPhrase,
)

LIST_LIMIT = 500


class ShadowingError(Exception):
    """Base error safe to convert to a closed public problem response."""


class ShadowingNotFound(ShadowingError):
    """The owner-scoped clip, or its excerpt, does not exist."""


class ShadowingInvalid(ShadowingError):
    """The command names something that is not there or is out of bounds."""


class ShadowingConflict(ShadowingError):
    """The clip already has an excerpt; excerpts are write-once."""


class ShadowingUnavailable(ShadowingError):
    """The database or the object store cannot answer right now."""


class ShadowingClipService:
    def __init__(
        self,
        session: AsyncSession,
        object_store: ObjectStore,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._objects = object_store
        self._clock = clock

    async def create(
        self, *, owner_id: int, command: ShadowingClipCommand
    ) -> ShadowingClipResponse:
        try:
            async with transaction_scope(self._session):
                now = self._clock()
                row = ShadowingClip(
                    owner_id=owner_id,
                    **_columns(command),
                    annotations=[],
                    preparation_state="pending",
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(row)
                await self._session.flush()
                return _clip(row)
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def list(self, *, owner_id: int) -> ShadowingClipPage:
        try:
            async with transaction_scope(self._session):
                rows = (
                    await self._session.scalars(
                        select(ShadowingClip)
                        .where(ShadowingClip.owner_id == owner_id)
                        .order_by(ShadowingClip.created_at.desc(), ShadowingClip.id.desc())
                        .limit(LIST_LIMIT)
                    )
                ).all()
                return ShadowingClipPage(items=tuple(_clip(row) for row in rows))
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def get(self, *, owner_id: int, clip_id: int) -> ShadowingClipResponse:
        try:
            async with transaction_scope(self._session):
                return _clip(await self._require(owner_id=owner_id, clip_id=clip_id))
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def replace(
        self, *, owner_id: int, clip_id: int, command: ShadowingClipCommand
    ) -> ShadowingClipResponse:
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id, lock=True)
                for name, value in _columns(command).items():
                    setattr(row, name, value)
                row.updated_at = self._clock()
                await self._session.flush()
                return _clip(row)
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def delete(self, *, owner_id: int, clip_id: int) -> None:
        """Remove the row. The excerpt object stays: the store is immutable and has no delete."""
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id, lock=True)
                await self._session.delete(row)
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def _require(
        self, *, owner_id: int, clip_id: int, lock: bool = False
    ) -> ShadowingClip:
        query = (
            select(ShadowingClip)
            .where(ShadowingClip.owner_id == owner_id)
            .where(ShadowingClip.id == clip_id)
        )
        if lock:
            query = query.with_for_update()
        row = await self._session.scalar(query)
        if row is None:
            raise ShadowingNotFound("the clip was not found")
        return row


def _columns(command: ShadowingClipCommand) -> dict[str, Any]:
    return {
        "title": command.title.strip(),
        "format": command.format,
        "skill_slug": command.skill_slug,
        "source_note": command.source_note.strip(),
        "license_note": command.license_note.strip(),
        "duration_ms": command.duration_ms,
        "phrases": [phrase.model_dump() for phrase in command.phrases],
    }


def _clip(row: ShadowingClip) -> ShadowingClipResponse:
    excerpt: ShadowingExcerptResponse | None = None
    if row.excerpt_object_key is not None:
        excerpt = ShadowingExcerptResponse(
            sha256=row.excerpt_object_key.rsplit("/", 1)[1],
            byte_length=cast(int, row.excerpt_byte_length),
            content_type=cast(Any, row.excerpt_content_type),
        )
    return ShadowingClipResponse(
        id=row.id,
        title=row.title,
        format=cast(Any, row.format),
        skill_slug=row.skill_slug,
        source_note=row.source_note,
        license_note=row.license_note,
        duration_ms=row.duration_ms,
        phrases=tuple(ShadowingPhrase.model_validate(item) for item in row.phrases),
        annotations=tuple(ShadowingAnnotation.model_validate(item) for item in row.annotations),
        preparation_state=cast(Any, row.preparation_state),
        excerpt=excerpt,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = [
    "ShadowingClipService",
    "ShadowingConflict",
    "ShadowingError",
    "ShadowingInvalid",
    "ShadowingNotFound",
    "ShadowingUnavailable",
]
```

- [ ] **Step 4: run and expect pass.**

```
~/.local/bin/uv run pytest -m integration apps/backend/tests/integration/shadowing apps/backend/tests/integration/test_migrations.py -q
```

Expected: 4 passed (1 shadowing, 3 in `test_migrations.py`; the migration round trip proves `downgrade` works).

- [ ] **Step 5: lint and types.**

```
~/.local/bin/uv run ruff check apps/backend/src/tamforge_backend/shadowing apps/backend/tests/integration/shadowing
~/.local/bin/uv run mypy apps/backend/src packages/protocol/src
```

Expected: both clean. The two `ShadowingPhrase(...)` lines in the test are over 100 characters; wrap each keyword argument onto its own line if ruff reports E501.

- [ ] **Step 6: commit.**

```
git add apps/backend/src/tamforge_backend/shadowing/service.py apps/backend/tests/integration/shadowing/__init__.py apps/backend/tests/integration/shadowing/test_shadowing_clips.py
git commit -m "feat(shadowing): owner-scoped clip service" -m "Create, list, get, replace and delete, every query filtered by owner. A clip of another owner answers not found. Deleting removes the row and leaves the immutable excerpt object in place." -m "Refs #363" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 4: Presigned excerpt upload, confirm and download

**Files**
- Modify: `apps/backend/src/tamforge_backend/shadowing/service.py`
- Test: `apps/backend/tests/unit/shadowing/test_shadowing_excerpt_key.py`
- Test: `apps/backend/tests/integration/shadowing/test_shadowing_clips.py` (append one test)

**Interfaces**
- Consumes: `ObjectStore.presign_put(PresignPutRequest) -> PresignedRequest`, `ObjectStore.stat(key) -> StoredObject | None`, `ObjectStore.presign_get(key, *, expires_seconds) -> str`, `storage.models.build_object_key`, `storage.models.ObjectStoreError`; `ExcerptUploadCommand`, `ExcerptUploadResponse`, `ExcerptConfirmCommand`, `ExcerptDownloadResponse` (Task 2); `learning.schemas.PresignedUploadResponse`.
- Produces:
  - `def excerpt_object_key(*, owner_id: int, clip_id: int, sha256: str) -> str`
  - `UPLOAD_EXPIRES_SECONDS = 300`, `DOWNLOAD_EXPIRES_SECONDS = 300`
  - `ShadowingClipService.presign_excerpt(self, *, owner_id: int, clip_id: int, command: ExcerptUploadCommand) -> ExcerptUploadResponse`
  - `ShadowingClipService.confirm_excerpt(self, *, owner_id: int, clip_id: int, command: ExcerptConfirmCommand) -> ShadowingClipResponse`
  - `ShadowingClipService.excerpt_download(self, *, owner_id: int, clip_id: int) -> ExcerptDownloadResponse`

**Independent of:** Task 5's route tests (they stub the service), but both edit nothing in common; Task 4 needs Task 3.

- [ ] **Step 1: write the failing unit test.** Create `apps/backend/tests/unit/shadowing/test_shadowing_excerpt_key.py`:

```python
from __future__ import annotations


def test_excerpt_key_is_scoped_by_class_owner_clip_and_hash() -> None:
    from tamforge_backend.shadowing.service import excerpt_object_key
    from tamforge_backend.storage.models import validate_object_key

    digest = "a" * 64
    key = excerpt_object_key(owner_id=3, clip_id=41, sha256=digest)

    assert key == f"shadowing-excerpt/3/clip-41/{digest}"
    assert validate_object_key(key) == key
    assert key != excerpt_object_key(owner_id=4, clip_id=41, sha256=digest)
    assert key != excerpt_object_key(owner_id=3, clip_id=42, sha256=digest)
```

- [ ] **Step 2: append the failing integration test** to `apps/backend/tests/integration/shadowing/test_shadowing_clips.py`:

```python
def test_excerpt_is_presigned_confirmed_once_and_downloaded(test_database_url: str) -> None:
    import hashlib
    from collections.abc import AsyncIterator

    from tamforge_backend.shadowing.schemas import ExcerptConfirmCommand, ExcerptUploadCommand
    from tamforge_backend.shadowing.service import (
        ShadowingClipService,
        ShadowingConflict,
        ShadowingInvalid,
        ShadowingNotFound,
        excerpt_object_key,
    )
    from tamforge_backend.storage.fake import InMemoryObjectStore

    body = b"not really audio, only bytes " * 64
    digest = hashlib.sha256(body).hexdigest()
    other_digest = hashlib.sha256(b"a different take").hexdigest()

    async def one_chunk(value: bytes) -> AsyncIterator[bytes]:
        yield value

    with _two_owners(test_database_url) as (owner_id, other_id):

        async def exercise(factory: Any) -> None:
            store = InMemoryObjectStore()
            async with factory() as session:
                service = ShadowingClipService(session, store, clock=lambda: NOW)
                clip = await service.create(owner_id=owner_id, command=_command())
                upload_command = ExcerptUploadCommand(
                    sha256=digest, byte_length=len(body), content_type="audio/mp4"
                )

                with pytest.raises(ShadowingNotFound):
                    await service.presign_excerpt(
                        owner_id=other_id, clip_id=clip.id, command=upload_command
                    )
                with pytest.raises(ShadowingNotFound):
                    await service.excerpt_download(owner_id=owner_id, clip_id=clip.id)

                signed = await service.presign_excerpt(
                    owner_id=owner_id, clip_id=clip.id, command=upload_command
                )
                assert signed.upload.method == "PUT" and signed.upload.expires_seconds == 300
                assert signed.upload.headers["content-type"] == "audio/mp4"
                assert signed.upload.headers["if-none-match"] == "*"
                assert f"clip-{clip.id}/{digest}" in signed.upload.url

                with pytest.raises(ShadowingInvalid):
                    await service.confirm_excerpt(
                        owner_id=owner_id,
                        clip_id=clip.id,
                        command=ExcerptConfirmCommand(sha256=digest),
                    )

                key = excerpt_object_key(owner_id=owner_id, clip_id=clip.id, sha256=digest)
                await store.put_immutable(
                    key=key,
                    body=one_chunk(body),
                    sha256=digest,
                    content_type="audio/mp4",
                    metadata={"owner-id": str(owner_id), "clip-id": str(clip.id)},
                )

            async with factory() as session:
                service = ShadowingClipService(session, store, clock=lambda: LATER)
                with pytest.raises(ShadowingNotFound):
                    await service.confirm_excerpt(
                        owner_id=other_id,
                        clip_id=clip.id,
                        command=ExcerptConfirmCommand(sha256=digest),
                    )
                confirmed = await service.confirm_excerpt(
                    owner_id=owner_id, clip_id=clip.id, command=ExcerptConfirmCommand(sha256=digest)
                )
                assert confirmed.excerpt is not None
                assert confirmed.excerpt.sha256 == digest
                assert confirmed.excerpt.byte_length == len(body)
                assert confirmed.excerpt.content_type == "audio/mp4"
                assert confirmed.updated_at == LATER

                again = await service.confirm_excerpt(
                    owner_id=owner_id, clip_id=clip.id, command=ExcerptConfirmCommand(sha256=digest)
                )
                assert again == confirmed
                with pytest.raises(ShadowingConflict):
                    await service.confirm_excerpt(
                        owner_id=owner_id,
                        clip_id=clip.id,
                        command=ExcerptConfirmCommand(sha256=other_digest),
                    )
                with pytest.raises(ShadowingConflict):
                    await service.presign_excerpt(
                        owner_id=owner_id,
                        clip_id=clip.id,
                        command=ExcerptUploadCommand(
                            sha256=other_digest, byte_length=16, content_type="video/mp4"
                        ),
                    )

                download = await service.excerpt_download(owner_id=owner_id, clip_id=clip.id)
                assert download.url.startswith("https://object-store.invalid/")
                assert digest in download.url and download.expires_seconds == 300
                assert download.sha256 == digest and download.byte_length == len(body)
                assert download.content_type == "audio/mp4"
                with pytest.raises(ShadowingNotFound):
                    await service.excerpt_download(owner_id=other_id, clip_id=clip.id)

                listed = await service.list(owner_id=owner_id)
                assert listed.items[0].excerpt == confirmed.excerpt

        _run(test_database_url, exercise)


def test_confirm_refuses_an_object_of_another_type(test_database_url: str) -> None:
    import hashlib
    from collections.abc import AsyncIterator

    from tamforge_backend.shadowing.schemas import ExcerptConfirmCommand
    from tamforge_backend.shadowing.service import (
        ShadowingClipService,
        ShadowingInvalid,
        excerpt_object_key,
    )
    from tamforge_backend.storage.fake import InMemoryObjectStore

    body = b"plain text pretending to be a clip"
    digest = hashlib.sha256(body).hexdigest()

    async def one_chunk(value: bytes) -> AsyncIterator[bytes]:
        yield value

    with _two_owners(test_database_url) as (owner_id, _):

        async def exercise(factory: Any) -> None:
            store = InMemoryObjectStore()
            async with factory() as session:
                service = ShadowingClipService(session, store, clock=lambda: NOW)
                clip = await service.create(owner_id=owner_id, command=_command())
                await store.put_immutable(
                    key=excerpt_object_key(owner_id=owner_id, clip_id=clip.id, sha256=digest),
                    body=one_chunk(body),
                    sha256=digest,
                    content_type="text/plain",
                    metadata={},
                )
                with pytest.raises(ShadowingInvalid):
                    await service.confirm_excerpt(
                        owner_id=owner_id,
                        clip_id=clip.id,
                        command=ExcerptConfirmCommand(sha256=digest),
                    )
                assert (await service.get(owner_id=owner_id, clip_id=clip.id)).excerpt is None

        _run(test_database_url, exercise)
```

- [ ] **Step 3: run both and see them fail.**

```
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing/test_shadowing_excerpt_key.py -q
~/.local/bin/uv run pytest -m integration apps/backend/tests/integration/shadowing -q
```

Expected: the unit test fails with `ImportError: cannot import name 'excerpt_object_key'`; the integration run shows 1 passed (Task 3) and 2 failed with the same `ImportError`.

- [ ] **Step 4: implement.** In `apps/backend/src/tamforge_backend/shadowing/service.py`:

Replace the import block's storage and model lines so the imports read:

```python
from ..database import transaction_scope
from ..learning.schemas import PresignedUploadResponse
from ..models.base import utc_now
from ..storage.models import ObjectStoreError, PresignPutRequest, build_object_key
from ..storage.ports import ObjectStore
from .models import EXCERPT_CONTENT_TYPES, MAX_EXCERPT_BYTES, ShadowingClip
from .schemas import (
    ExcerptConfirmCommand,
    ExcerptDownloadResponse,
    ExcerptUploadCommand,
    ExcerptUploadResponse,
    ShadowingAnnotation,
    ShadowingClipCommand,
    ShadowingClipPage,
    ShadowingClipResponse,
    ShadowingExcerptResponse,
    ShadowingPhrase,
)

LIST_LIMIT = 500
UPLOAD_EXPIRES_SECONDS = 300
DOWNLOAD_EXPIRES_SECONDS = 300
```

Add the key builder directly under the error classes, before `class ShadowingClipService`:

```python
def excerpt_object_key(*, owner_id: int, clip_id: int, sha256: str) -> str:
    """The only key an excerpt can have: class, owner, clip and the hash of its bytes."""
    return build_object_key(
        artifact_class="shadowing-excerpt",
        owner_id=str(owner_id),
        logical_id=f"clip-{clip_id}",
        sha256=sha256,
    )
```

Add these three methods to `ShadowingClipService`, after `delete` and before `_require`:

```python
    async def presign_excerpt(
        self, *, owner_id: int, clip_id: int, command: ExcerptUploadCommand
    ) -> ExcerptUploadResponse:
        """Sign one PUT that accepts exactly the declared bytes, type and hash."""
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id)
                if row.excerpt_object_key is not None:
                    raise ShadowingConflict("the clip already has its excerpt")
                signed = await self._objects.presign_put(
                    PresignPutRequest(
                        key=excerpt_object_key(
                            owner_id=owner_id, clip_id=clip_id, sha256=command.sha256
                        ),
                        sha256=command.sha256,
                        byte_length=command.byte_length,
                        content_type=command.content_type,
                        metadata={"owner-id": str(owner_id), "clip-id": str(clip_id)},
                        expires_seconds=UPLOAD_EXPIRES_SECONDS,
                    )
                )
                return ExcerptUploadResponse(
                    upload=PresignedUploadResponse(
                        url=signed.url,
                        method="PUT",
                        headers=dict(signed.headers),
                        expires_seconds=signed.expires_seconds,
                    )
                )
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None
        except ObjectStoreError:
            raise ShadowingUnavailable("the excerpt store is unavailable") from None

    async def confirm_excerpt(
        self, *, owner_id: int, clip_id: int, command: ExcerptConfirmCommand
    ) -> ShadowingClipResponse:
        """Point the clip at its uploaded excerpt, once the store has the object.
        Repeating it for the same bytes changes nothing; other bytes are a conflict."""
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id, lock=True)
                key = excerpt_object_key(owner_id=owner_id, clip_id=clip_id, sha256=command.sha256)
                if row.excerpt_object_key is not None:
                    if row.excerpt_object_key == key:
                        return _clip(row)
                    raise ShadowingConflict("the clip already has its excerpt")
                stored = await self._objects.stat(key)
                if stored is None:
                    raise ShadowingInvalid("the excerpt was not uploaded")
                if (
                    stored.content_type not in EXCERPT_CONTENT_TYPES
                    or not 1 <= stored.byte_length <= MAX_EXCERPT_BYTES
                ):
                    raise ShadowingInvalid("the uploaded excerpt is not an accepted media file")
                row.excerpt_object_key = key
                row.excerpt_content_type = stored.content_type
                row.excerpt_byte_length = stored.byte_length
                row.updated_at = self._clock()
                await self._session.flush()
                return _clip(row)
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None
        except ObjectStoreError:
            raise ShadowingUnavailable("the excerpt store is unavailable") from None

    async def excerpt_download(self, *, owner_id: int, clip_id: int) -> ExcerptDownloadResponse:
        """A short-lived signed GET for the Mac's local playback cache."""
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id)
                if row.excerpt_object_key is None:
                    raise ShadowingNotFound("the clip has no excerpt yet")
                url = await self._objects.presign_get(
                    row.excerpt_object_key, expires_seconds=DOWNLOAD_EXPIRES_SECONDS
                )
                return ExcerptDownloadResponse(
                    url=url,
                    expires_seconds=DOWNLOAD_EXPIRES_SECONDS,
                    sha256=row.excerpt_object_key.rsplit("/", 1)[1],
                    byte_length=cast(int, row.excerpt_byte_length),
                    content_type=cast(Any, row.excerpt_content_type),
                )
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None
        except ObjectStoreError:
            raise ShadowingUnavailable("the excerpt store is unavailable") from None
```

Extend `__all__` to:

```python
__all__ = [
    "DOWNLOAD_EXPIRES_SECONDS",
    "UPLOAD_EXPIRES_SECONDS",
    "ShadowingClipService",
    "ShadowingConflict",
    "ShadowingError",
    "ShadowingInvalid",
    "ShadowingNotFound",
    "ShadowingUnavailable",
    "excerpt_object_key",
]
```

- [ ] **Step 5: run and expect pass.**

```
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing -q
~/.local/bin/uv run pytest -m integration apps/backend/tests/integration/shadowing -q
```

Expected: unit all passed; integration 3 passed.

- [ ] **Step 6: lint and types.**

```
~/.local/bin/uv run ruff check apps/backend/src/tamforge_backend/shadowing apps/backend/tests/unit/shadowing apps/backend/tests/integration/shadowing
~/.local/bin/uv run mypy apps/backend/src packages/protocol/src
```

Expected: both clean.

- [ ] **Step 7: commit.**

```
git add apps/backend/src/tamforge_backend/shadowing/service.py apps/backend/tests/unit/shadowing/test_shadowing_excerpt_key.py apps/backend/tests/integration/shadowing/test_shadowing_clips.py
git commit -m "feat(shadowing): presigned excerpt upload, confirm and download" -m "One signed PUT pins the key, length, content type and SHA-256; confirm stats the object and re-checks type and size before the row points at it; download is a five-minute signed GET. The excerpt is write-once and the key never leaves the server." -m "Refs #363" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 5: Routes, registration and problem responses

**Files**
- Create: `apps/backend/src/tamforge_backend/shadowing/routes.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Test: `apps/backend/tests/unit/shadowing/test_shadowing_routes.py`

**Interfaces**
- Consumes: `ShadowingClipService` and the five error classes (Tasks 3 and 4); all schemas (Task 2); `auth.dependencies.get_authenticated_owner`, `require_csrf_owner`; `auth.schemas.AuthenticatedOwner`, `ProblemResponse`; `database.get_db_session`; `storage.dependencies.get_object_store`; `storage.models.ObjectStoreError`.
- Produces: `shadowing.routes.router` (prefix `/api/v1/shadowing-clips`, tag `shadowing`), `get_shadowing_service(request: Request, session: AsyncSession) -> ShadowingClipService`, `shadowing_problem_response(exc: Exception) -> JSONResponse`, `shadowing_exception_handler(request: Request, exc: Exception) -> JSONResponse`; both registered in `api.register_routes`.

**Independent of:** Task 4's implementation details (the tests stub the service), but it imports the service module, so Tasks 3 and 4 must be merged first.

- [ ] **Step 1: write the failing test.** Create `apps/backend/tests/unit/shadowing/test_shadowing_routes.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.learning.schemas import PresignedUploadResponse
from tamforge_backend.main import create_app
from tamforge_backend.shadowing.routes import get_shadowing_service
from tamforge_backend.shadowing.schemas import (
    ExcerptConfirmCommand,
    ExcerptDownloadResponse,
    ExcerptUploadCommand,
    ExcerptUploadResponse,
    ShadowingClipCommand,
    ShadowingClipPage,
    ShadowingClipResponse,
    ShadowingExcerptResponse,
)
from tamforge_backend.shadowing.service import (
    ShadowingConflict,
    ShadowingInvalid,
    ShadowingNotFound,
    ShadowingUnavailable,
)

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)
NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
DIGEST = "a" * 64
BODY: dict[str, Any] = {
    "title": "QBR opening",
    "format": "solo",
    "skill_slug": "english_fluency",
    "source_note": "Recorded talk, minute 3",
    "license_note": "CC BY 4.0",
    "duration_ms": 45_000,
    "phrases": [
        {"index": 0, "start_ms": 0, "end_ms": 2_000, "text": "Thanks for joining.", "enabled": True}
    ],
}


def _clip(command: ShadowingClipCommand, clip_id: int = 7, *, uploaded: bool = False) -> ShadowingClipResponse:
    return ShadowingClipResponse(
        id=clip_id,
        title=command.title,
        format=command.format,
        skill_slug=command.skill_slug,
        source_note=command.source_note,
        license_note=command.license_note,
        duration_ms=command.duration_ms,
        phrases=command.phrases,
        annotations=(),
        preparation_state="pending",
        excerpt=(
            ShadowingExcerptResponse(sha256=DIGEST, byte_length=1_024, content_type="audio/mp4")
            if uploaded
            else None
        ),
        created_at=NOW,
        updated_at=NOW,
    )


class StubService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.command = ShadowingClipCommand.model_validate(BODY)

    def _record(self, name: str, **values: object) -> None:
        self.calls.append((name, values))
        if self.error is not None:
            raise self.error

    async def list(self, *, owner_id: int) -> ShadowingClipPage:
        self._record("list", owner_id=owner_id)
        return ShadowingClipPage(items=(_clip(self.command),))

    async def create(self, *, owner_id: int, command: ShadowingClipCommand) -> ShadowingClipResponse:
        self._record("create", owner_id=owner_id, command=command)
        return _clip(command)

    async def get(self, *, owner_id: int, clip_id: int) -> ShadowingClipResponse:
        self._record("get", owner_id=owner_id, clip_id=clip_id)
        return _clip(self.command, clip_id)

    async def replace(
        self, *, owner_id: int, clip_id: int, command: ShadowingClipCommand
    ) -> ShadowingClipResponse:
        self._record("replace", owner_id=owner_id, clip_id=clip_id, command=command)
        return _clip(command, clip_id)

    async def delete(self, *, owner_id: int, clip_id: int) -> None:
        self._record("delete", owner_id=owner_id, clip_id=clip_id)

    async def presign_excerpt(
        self, *, owner_id: int, clip_id: int, command: ExcerptUploadCommand
    ) -> ExcerptUploadResponse:
        self._record("presign", owner_id=owner_id, clip_id=clip_id, command=command)
        return ExcerptUploadResponse(
            upload=PresignedUploadResponse(
                url="https://object-store.invalid/upload?signed=1",
                method="PUT",
                headers={"content-type": command.content_type},
                expires_seconds=300,
            )
        )

    async def confirm_excerpt(
        self, *, owner_id: int, clip_id: int, command: ExcerptConfirmCommand
    ) -> ShadowingClipResponse:
        self._record("confirm", owner_id=owner_id, clip_id=clip_id, command=command)
        return _clip(self.command, clip_id, uploaded=True)

    async def excerpt_download(self, *, owner_id: int, clip_id: int) -> ExcerptDownloadResponse:
        self._record("download", owner_id=owner_id, clip_id=clip_id)
        return ExcerptDownloadResponse(
            url="https://object-store.invalid/download?signed=1",
            expires_seconds=300,
            sha256=DIGEST,
            byte_length=1_024,
            content_type="audio/mp4",
        )


def _client() -> tuple[TestClient, StubService]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubService()
    app.dependency_overrides[get_shadowing_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_clip_crud_round_trip_is_owner_scoped_and_never_cached() -> None:
    client, service = _client()
    with client:
        created = client.post("/api/v1/shadowing-clips", json=BODY)
        listed = client.get("/api/v1/shadowing-clips")
        fetched = client.get("/api/v1/shadowing-clips/7")
        replaced = client.put("/api/v1/shadowing-clips/7", json={**BODY, "title": "Take 2"})
        deleted = client.delete("/api/v1/shadowing-clips/7")

    assert created.status_code == 201, created.text
    assert created.json()["excerpt"] is None and created.json()["annotations"] == []
    assert created.json()["preparation_state"] == "pending"
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1
    assert fetched.status_code == 200 and fetched.json()["id"] == 7
    assert replaced.status_code == 200 and replaced.json()["title"] == "Take 2"
    assert deleted.status_code == 204 and deleted.content == b""
    for response in (created, listed, fetched, replaced, deleted):
        assert response.headers["cache-control"] == "no-store"
    assert [name for name, _ in service.calls] == ["create", "list", "get", "replace", "delete"]
    assert all(values["owner_id"] == 1 for _, values in service.calls)
    assert service.calls[3][1]["clip_id"] == 7


def test_excerpt_upload_confirm_and_download() -> None:
    client, service = _client()
    with client:
        signed = client.post(
            "/api/v1/shadowing-clips/7/excerpt/upload",
            json={"sha256": DIGEST, "byte_length": 1_024, "content_type": "audio/mp4"},
        )
        confirmed = client.post(
            "/api/v1/shadowing-clips/7/excerpt/confirm", json={"sha256": DIGEST}
        )
        download = client.get("/api/v1/shadowing-clips/7/excerpt/download")

    assert signed.status_code == 200, signed.text
    assert signed.json()["upload"]["method"] == "PUT"
    assert signed.json()["upload"]["headers"] == {"content-type": "audio/mp4"}
    assert confirmed.status_code == 200 and confirmed.json()["excerpt"]["sha256"] == DIGEST
    assert download.status_code == 200 and download.json()["expires_seconds"] == 300
    assert "object_key" not in signed.text + confirmed.text + download.text
    for response in (signed, confirmed, download):
        assert response.headers["cache-control"] == "no-store"
    assert [name for name, _ in service.calls] == ["presign", "confirm", "download"]


def test_invalid_commands_never_reach_the_service() -> None:
    client, service = _client()
    overlapping = [
        {"index": 0, "start_ms": 0, "end_ms": 2_000, "text": "One.", "enabled": True},
        {"index": 1, "start_ms": 1_000, "end_ms": 3_000, "text": "Two.", "enabled": True},
    ]
    with client:
        responses = [
            client.post("/api/v1/shadowing-clips", json={**BODY, "title": ""}),
            client.post("/api/v1/shadowing-clips", json={**BODY, "format": "trio"}),
            client.post("/api/v1/shadowing-clips", json={**BODY, "phrases": overlapping}),
            client.put("/api/v1/shadowing-clips/7", json={**BODY, "duration_ms": 120_001}),
            client.post("/api/v1/shadowing-clips", json={**BODY, "x": 1}),
            client.post(
                "/api/v1/shadowing-clips/7/excerpt/upload",
                json={"sha256": DIGEST, "byte_length": 1_024, "content_type": "audio/mpeg"},
            ),
            client.post(
                "/api/v1/shadowing-clips/7/excerpt/upload",
                json={"sha256": DIGEST, "byte_length": 104_857_601, "content_type": "video/mp4"},
            ),
            client.post("/api/v1/shadowing-clips/7/excerpt/confirm", json={"sha256": "nope"}),
        ]

    assert {response.status_code for response in responses} == {422}
    assert service.calls == []


def test_service_errors_are_closed_problems() -> None:
    client, service = _client()
    expected = (
        (ShadowingNotFound("internal clip detail"), 404, "shadowing_clip_not_found"),
        (ShadowingInvalid("internal clip detail"), 422, "invalid_shadowing_command"),
        (ShadowingConflict("internal clip detail"), 409, "shadowing_conflict"),
        (ShadowingUnavailable("internal clip detail"), 503, "shadowing_unavailable"),
    )
    with client:
        for error, status, code in expected:
            service.error = error
            response = client.post(
                "/api/v1/shadowing-clips/9/excerpt/confirm", json={"sha256": DIGEST}
            )
            assert response.status_code == status
            assert response.json()["code"] == code
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.headers["cache-control"] == "no-store"
            assert "internal clip detail" not in response.text


def test_the_contract_lists_every_shadowing_operation() -> None:
    client, _ = _client()
    with client:
        paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]

    assert set(paths["/api/v1/shadowing-clips"]) == {"get", "post"}
    assert set(paths["/api/v1/shadowing-clips/{clip_id}"]) == {"get", "put", "delete"}
    assert set(paths["/api/v1/shadowing-clips/{clip_id}/excerpt/upload"]) == {"post"}
    assert set(paths["/api/v1/shadowing-clips/{clip_id}/excerpt/confirm"]) == {"post"}
    assert set(paths["/api/v1/shadowing-clips/{clip_id}/excerpt/download"]) == {"get"}
```

- [ ] **Step 2: run it and see it fail.**

```
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing/test_shadowing_routes.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'tamforge_backend.shadowing.routes'`.

- [ ] **Step 3: write the routes.** `apps/backend/src/tamforge_backend/shadowing/routes.py`:

```python
"""Shadowing clip endpoints: the clips themselves and the signed upload and download of
each clip's excerpt. The excerpt bytes never pass through this process."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from ..storage.dependencies import get_object_store
from ..storage.models import ObjectStoreError
from .schemas import (
    ExcerptConfirmCommand,
    ExcerptDownloadResponse,
    ExcerptUploadCommand,
    ExcerptUploadResponse,
    ShadowingClipCommand,
    ShadowingClipPage,
    ShadowingClipResponse,
)
from .service import (
    ShadowingClipService,
    ShadowingConflict,
    ShadowingInvalid,
    ShadowingNotFound,
    ShadowingUnavailable,
)

router = APIRouter(prefix="/api/v1/shadowing-clips", tags=["shadowing"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_shadowing_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ShadowingClipService:
    try:
        object_store = get_object_store(request)
    except (ObjectStoreError, ValueError):
        raise ShadowingUnavailable("the excerpt store is unavailable") from None
    return ShadowingClipService(session, object_store)


@router.get("", response_model=ShadowingClipPage)
async def list_shadowing_clips(
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ShadowingClipPage:
    result = await service.list(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.post("", response_model=ShadowingClipResponse, status_code=201)
async def create_shadowing_clip(
    command: ShadowingClipCommand,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ShadowingClipResponse:
    """Create the clip without its media. The excerpt follows through upload and confirm."""
    result = await service.create(owner_id=owner.owner_id, command=command)
    _prevent_storage(response)
    return result


@router.get("/{clip_id}", response_model=ShadowingClipResponse)
async def get_shadowing_clip(
    clip_id: int,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ShadowingClipResponse:
    result = await service.get(owner_id=owner.owner_id, clip_id=clip_id)
    _prevent_storage(response)
    return result


@router.put("/{clip_id}", response_model=ShadowingClipResponse)
async def replace_shadowing_clip(
    clip_id: int,
    command: ShadowingClipCommand,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ShadowingClipResponse:
    """Replace everything the learner decides about the clip; the excerpt is untouched."""
    result = await service.replace(owner_id=owner.owner_id, clip_id=clip_id, command=command)
    _prevent_storage(response)
    return result


@router.delete("/{clip_id}", status_code=204)
async def delete_shadowing_clip(
    clip_id: int,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> Response:
    await service.delete(owner_id=owner.owner_id, clip_id=clip_id)
    response = Response(status_code=204)
    _prevent_storage(response)
    return response


@router.post("/{clip_id}/excerpt/upload", response_model=ExcerptUploadResponse)
async def presign_shadowing_excerpt(
    clip_id: int,
    command: ExcerptUploadCommand,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ExcerptUploadResponse:
    """A signed PUT for exactly the declared bytes. Send every returned header with it."""
    result = await service.presign_excerpt(
        owner_id=owner.owner_id, clip_id=clip_id, command=command
    )
    _prevent_storage(response)
    return result


@router.post("/{clip_id}/excerpt/confirm", response_model=ShadowingClipResponse)
async def confirm_shadowing_excerpt(
    clip_id: int,
    command: ExcerptConfirmCommand,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ShadowingClipResponse:
    """Attach the uploaded excerpt to the clip. Safe to repeat for the same bytes."""
    result = await service.confirm_excerpt(
        owner_id=owner.owner_id, clip_id=clip_id, command=command
    )
    _prevent_storage(response)
    return result


@router.get("/{clip_id}/excerpt/download", response_model=ExcerptDownloadResponse)
async def download_shadowing_excerpt(
    clip_id: int,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ExcerptDownloadResponse:
    result = await service.excerpt_download(owner_id=owner.owner_id, clip_id=clip_id)
    _prevent_storage(response)
    return result


def shadowing_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, ShadowingNotFound):
        status, code, title = 404, "shadowing_clip_not_found", "Shadowing clip not found"
    elif isinstance(exc, ShadowingInvalid):
        status, code, title = 422, "invalid_shadowing_command", "Invalid shadowing command"
    elif isinstance(exc, ShadowingConflict):
        status, code, title = 409, "shadowing_conflict", "Shadowing clip already has its excerpt"
    elif isinstance(exc, ShadowingUnavailable):
        status, code, title = 503, "shadowing_unavailable", "Shadowing unavailable"
    else:
        status, code, title = 500, "shadowing_error", "Shadowing operation failed"
    problem = ProblemResponse(
        type=f"https://tamforge.local/problems/{code}",
        title=title,
        status=status,
        detail=title + ".",
        code=code,
    )
    response = JSONResponse(
        problem.model_dump(), status_code=status, media_type="application/problem+json"
    )
    _prevent_storage(response)
    return response


async def shadowing_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return shadowing_problem_response(exc)


__all__ = [
    "get_shadowing_service",
    "router",
    "shadowing_exception_handler",
    "shadowing_problem_response",
]
```

- [ ] **Step 4: register in `api.py`.** In `apps/backend/src/tamforge_backend/api.py`:

After the line `from .roadmaps.routes import router as roadmap_router` add:

```python
from .shadowing.routes import router as shadowing_router
from .shadowing.routes import shadowing_exception_handler
from .shadowing.service import ShadowingError
```

After `app.include_router(cards_router)` add:

```python
    app.include_router(shadowing_router)
```

After `app.add_exception_handler(CardsError, cards_exception_handler)` add:

```python
    app.add_exception_handler(ShadowingError, shadowing_exception_handler)
```

- [ ] **Step 5: run and expect pass.**

```
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing -q
```

Expected: all passed. `scripts/ci/tests/test_check_openapi.py` and the `openapi` check now fail on purpose; Task 6 fixes them.

- [ ] **Step 6: lint and types.**

```
~/.local/bin/uv run ruff check apps/backend/src/tamforge_backend apps/backend/tests/unit/shadowing
~/.local/bin/uv run mypy apps/backend/src packages/protocol/src
```

Expected: both clean. Ruff's import sorter (`I`) wants the three `shadowing` imports between `roadmaps` and `speech`; the position given in Step 4 satisfies it. If the `_clip` helper signature or the `create` stub in the test exceed 100 characters, wrap the parameters one per line.

- [ ] **Step 7: commit.**

```
git add apps/backend/src/tamforge_backend/shadowing/routes.py apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/shadowing/test_shadowing_routes.py
git commit -m "feat(shadowing): clip and excerpt endpoints under /api/v1/shadowing-clips" -m "List, create, get, replace and delete a clip, plus the signed upload, confirm and download of its excerpt. Mutations need the CSRF owner. Service errors become closed problem responses that never echo internal detail." -m "Refs #363" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 6: Regenerate the native OpenAPI contract

**Files**
- Modify: `apps/macos/TAMForge/openapi.yaml` (generated, never by hand)
- Modify: `scripts/ci/tests/test_check_openapi.py` (`FROZEN_OPENAPI_SHA256`)

**Interfaces**
- Consumes: the app built by `create_app` with the shadowing router (Task 5).
- Produces: a native contract with the five shadowing paths and the components `ShadowingClipCommand`, `ShadowingClipResponse`, `ShadowingClipPage`, `ShadowingPhrase`, `ShadowingAnnotation`, `ShadowingExcerptResponse`, `ExcerptUploadCommand`, `ExcerptUploadResponse`, `ExcerptConfirmCommand`, `ExcerptDownloadResponse`.

**Independent of:** none (needs Task 5).

- [ ] **Step 1: see the two gates fail.**

```
~/.local/bin/uv run python scripts/ci/check_openapi.py
~/.local/bin/uv run pytest scripts/ci/tests/test_check_openapi.py -q
```

Expected: the first prints `Native OpenAPI input is out of date.` and exits 1; the second fails in the test that compares against `FROZEN_OPENAPI_SHA256`.

- [ ] **Step 2: regenerate the native input.**

```
~/.local/bin/uv run python scripts/ci/check_openapi.py --write
```

Expected: `updated apps/macos/TAMForge/openapi.yaml`.

- [ ] **Step 3: compute the new frozen hash.**

```
~/.local/bin/uv run python -c "import hashlib, importlib.util; s = importlib.util.spec_from_file_location('check_openapi', 'scripts/ci/check_openapi.py'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); print(hashlib.sha256(m.normalized_openapi_document()).hexdigest())"
```

Copy the 64-character output. In `scripts/ci/tests/test_check_openapi.py` replace the value of `FROZEN_OPENAPI_SHA256` (line 12) with it. This hash is of the full 3.1 document, not of `openapi.yaml`; do not hash the file.

- [ ] **Step 4: check the generated contract for the Swift traps.**

```
~/.local/bin/uv run python - <<'PY'
import json
from pathlib import Path

document = json.loads(Path("apps/macos/TAMForge/openapi.yaml").read_text())
schemas = document["components"]["schemas"]
names = [name for name in schemas if name.startswith(("Shadowing", "Excerpt"))]
assert len(names) == 10, names
for name in names:
    for field, schema in schemas[name].get("properties", {}).items():
        assert schema.get("default", 0) is not None, f"{name}.{field} has a null default"
        assert schema.get("type") != "null", f"{name}.{field} is typed null"
clip = schemas["ShadowingClipResponse"]
assert "excerpt" in clip["required"] and clip["properties"]["excerpt"]["nullable"] is True
assert set(schemas["ShadowingClipCommand"]["required"]) == {
    "title", "format", "skill_slug", "duration_ms"
}
print("shadowing contract is generator-safe:", sorted(names))
PY
```

Expected: the final `print` line and no assertion error. (`openapi.yaml` holds JSON, which is valid YAML; `check_openapi.py` writes it with `json.dumps`.)

- [ ] **Step 5: run and expect pass.**

```
~/.local/bin/uv run python scripts/ci/check_openapi.py
~/.local/bin/uv run pytest scripts/ci/tests/test_check_openapi.py -q
```

Expected: `Native OpenAPI input matches the backend schema.` and all tests passed.

- [ ] **Step 6: full local verify gate.**

```
~/.local/bin/uv run ruff check .
~/.local/bin/uv run mypy apps/backend/src packages/protocol/src
MYPYPATH=apps/backend/src:packages/protocol/src ~/.local/bin/uv run mypy scripts/ci/check_openapi.py scripts/ci/check_repository_policy.py scripts/ci/verify_bootstrap.py scripts/ci/verify_compose.py scripts/dev/seed_foundation_demo.py
~/.local/bin/uv run pytest apps/backend/tests/unit/shadowing apps/backend/tests/unit/roadmaps/test_curriculum_schema.py apps/backend/tests/unit/cards apps/backend/tests/unit/practice scripts/ci/tests -m "not integration" -q
~/.local/bin/uv run python scripts/ci/check_repository_policy.py
~/.local/bin/uv run pytest -m integration apps/backend/tests/integration/shadowing apps/backend/tests/integration/test_migrations.py -q
```

Expected: everything clean and green. The Swift types themselves are generated at build time by the pinned OpenAPI generator plugin from `openapi.yaml`; that compile runs in CI's `native` job, not locally.

- [ ] **Step 7: commit.**

```
git add apps/macos/TAMForge/openapi.yaml scripts/ci/tests/test_check_openapi.py
git commit -m "chore(contract): regenerate the native OpenAPI contract for shadowing clips" -m "Refs #363" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

**Acceptance criteria of #363 mapped to tasks**

| Criterion | Task |
| --- | --- |
| New `shadowing/` package with `ShadowingClip` (title, format, `skill_slug`, source note, license note, object-store key, duration, `phrases` JSONB, `annotations` JSONB, preparation state) | Task 1 (`models.py`: `title`, `format`, `skill_slug`, `source_note`, `license_note`, `excerpt_object_key`, `duration_ms`, `phrases`, `annotations`, `preparation_state`) |
| Alembic revision with an id of 32 characters or fewer | Task 1 (`20260919_0036_shadowing_clips`, 29; asserted by `test_migration_id_fits_alembic_version_and_follows_the_current_head`; head pin moved) |
| CRUD routes under `/api/v1/shadowing-clips` registered in `api.py` | Task 3 (service), Task 5 (routes, `include_router`, `add_exception_handler`) |
| Presigned upload and download of the excerpt through the existing object-store port | Task 4 (`presign_put`, `stat`, `presign_get` on `ObjectStore`; no new port method), Task 5 (three excerpt routes) |
| Swift contracts regenerate cleanly | Task 6 (`check_openapi.py --write`, frozen hash, generator-safety script); compile proven by CI `native` |
| Optional fields avoid bare `None` defaults | Task 2 (`test_no_field_reaches_the_swift_generator_with_a_bare_none_default`; the only nullable field is the required-nullable `ShadowingClipResponse.excerpt`; no optional request field exists), re-checked on the generated document in Task 6 Step 4 |
| Verification: `pytest -k shadowing` | Replaced by the named-directory commands in "Local verify gate" because the whole-tree run collides at collection |
| Verification: contract generation job passes | Task 6 Steps 5 and 6 mirror the `openapi` job |

Decisions from the brief: no URL fetch (no such field or route exists); bytes never in Postgres (Task 1 stores a key; Task 4 signs, the API never sees the body); owner scoping (every query in `_require` and `list` filters `owner_id`; cross-owner access is asserted in Tasks 3 and 4); phrase validation ordered, non-overlapping, inside the duration (Task 2, table test); bounded content types and size (Task 2 on the command, Task 4 re-checks the stored object, Task 1 check constraints as the last line).

**Placeholder scan.** No "TBD", no "similar to task N", no unspecified error handling: every `except` names its exception and its replacement. Two values are produced at execution time and cannot be written here: the new `FROZEN_OPENAPI_SHA256` (Task 6 Step 3 gives the exact command that prints it) and the private Postgres port (any free port in 49152 to 65535; 54363 is given). Three steps note a possible E501 wrap on long test lines; the instruction is explicit (one parameter or keyword per line).

**Type consistency.**
- Service class is `ShadowingClipService` everywhere (Tasks 3, 4, 5); constructor `(session, object_store, *, clock)` is identical in the integration tests and in `get_shadowing_service`.
- Method names match between service, stub and routes: `create`, `list`, `get`, `replace`, `delete`, `presign_excerpt`, `confirm_excerpt`, `excerpt_download`.
- Errors: `ShadowingError` base with `ShadowingNotFound`, `ShadowingInvalid`, `ShadowingConflict`, `ShadowingUnavailable`; `api.py` registers the base, the problem mapper handles all four plus the fallback.
- Constants: `MAX_CLIP_DURATION_MS = 120_000` and `MAX_EXCERPT_BYTES = 104_857_600` are defined once in `models.py`, re-exported by `schemas.py`, and equal the literals in the check constraints (`120000`, `104857600`) and in the route test (`104_857_601` refused, `120_001` refused).
- `EXCERPT_CONTENT_TYPES` tuple (models) equals the `ExcerptContentType` literal (schemas) equals the SQL `IN` list (model and migration).
- Model and migration agree column by column, constraint name by constraint name (16 columns, 2 unique constraints, 1 foreign key, 10 check constraints, 1 index).
- `ShadowingPhrase.enabled` is required (no default) so the response schema marks it required; the brief's phrase fields `index`, `start_ms`, `end_ms`, `text`, `enabled` are all present.
- `title` is limited to 200 characters in the schema and 800 bytes in the database (4 bytes per character worst case); notes 500 characters and 2000 bytes.

**Fixed inline during review.** `end_ms` was first declared `gt=0`; changed to `ge=1` so the generated schema carries a plain `minimum` and does not depend on the exclusive-bound lowering in `check_openapi.py`. The confirm step first returned 404 for a missing object; changed to `ShadowingInvalid` (422) so 404 always means "no such clip or no excerpt yet" and a client can tell a wrong id from an upload that did not land.
