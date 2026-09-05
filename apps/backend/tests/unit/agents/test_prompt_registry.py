from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError


def test_exact_utf8_prompt_identity():
    from tamforge_backend.agents.hashing import prompt_bytes

    assert sha256(prompt_bytes("é\r\n")).digest() == sha256(b"\xc3\xa9\r\n").digest()
    assert prompt_bytes("e\u0301") != prompt_bytes("é")
    with pytest.raises(ValueError):
        prompt_bytes("x" * (1024 * 1024 + 1))


def test_canonical_json_has_sorted_keys_exact_unicode_and_plain_numbers():
    from tamforge_backend.agents.hashing import canonical_bytes

    assert canonical_bytes({"z": [1.0, Decimal("0.0100"), -0.0], "é": "e\u0301"}) == (
        '{"z":[1,0.01,0],"é":"é"}'.encode()
    )
    assert canonical_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "x"}, "\x00", "\ud800"])
def test_canonical_rejects_nonportable_json(value):
    from tamforge_backend.agents.hashing import canonical_bytes

    with pytest.raises(ValueError):
        canonical_bytes(value)


@pytest.mark.parametrize("owner", [True, "1", 0, -1])
def test_registry_identity_is_strict(owner):
    from tamforge_backend.agents.contracts import Publication

    with pytest.raises(ValidationError):
        Publication(owner_id=owner, key="urn:tamforge:agent:test", version="v1")


def test_registry_replays_exact_bytes_and_rejects_changed_publication():
    import asyncio
    from contextlib import asynccontextmanager

    from tamforge_backend.agents.contracts import ImmutableVersionConflict, InvalidProvenance
    from tamforge_backend.agents.models import PromptVersion
    from tamforge_backend.agents.prompt_registry import PromptRegistry

    class Session:
        def __init__(self):
            self.rows = []

        @asynccontextmanager
        async def begin(self):
            yield self

        async def scalar(self, statement):
            if "FROM owners" in str(statement):
                return 1
            return self.rows[0] if self.rows else None

        def add(self, row):
            self.rows.append(row)

        async def flush(self):
            self.rows[-1].id = 1
            self.rows[-1].hash_format = 1

    async def exercise():
        session = Session()
        registry = PromptRegistry(session)
        first = await registry.publish_prompt(
            owner_id=1, key="reviewer", version="v1", content="prompt A"
        )
        second = await registry.publish_prompt(
            owner_id=1, key="reviewer", version="v1", content="prompt A"
        )
        assert isinstance(first, PromptVersion)
        assert first.id == second.id and len(session.rows) == 1
        assert first.content_hash == sha256(b"prompt A").digest()
        with pytest.raises(ImmutableVersionConflict):
            await registry.publish_prompt(
                owner_id=1, key="reviewer", version="v1", content="prompt B"
            )
        assert first.canonical_json == "prompt A"
        with pytest.raises(InvalidProvenance):
            await registry.publish_prompt(
                owner_id=True, key="reviewer", version="v1", content="private"
            )

    asyncio.run(exercise())


def test_lookup_verification_rejects_forged_bytes():
    from tamforge_backend.agents.contracts import InvalidProvenance
    from tamforge_backend.agents.models import PromptVersion
    from tamforge_backend.agents.prompt_registry import verified

    row = PromptVersion(
        owner_id=1,
        key="a",
        version="1",
        canonical_json="prompt",
        content_hash=b"x" * 32,
        hash_format=1,
    )
    with pytest.raises(InvalidProvenance):
        verified(row)


def test_all_provenance_tables_have_unique_constraint_names_and_orm_mutation_guards():
    from sqlalchemy.orm import make_transient_to_detached
    from tamforge_backend.agents.contracts import ImmutableVersionConflict
    from tamforge_backend.agents.models import RECORD_TYPES
    from tamforge_backend.models import load_all_models

    load_all_models()
    for model in RECORD_TYPES:
        names = [item.name for item in model.__table__.constraints]
        assert len(names) == len(set(names))
        row = model(id=1, owner_id=1, canonical_json="{}", content_hash=b"x" * 32, hash_format=1)
        make_transient_to_detached(row)
        with pytest.raises(ImmutableVersionConflict):
            model.__mapper__.dispatch.before_update(model.__mapper__, None, row._sa_instance_state)
        with pytest.raises(ImmutableVersionConflict):
            model.__mapper__.dispatch.before_delete(model.__mapper__, None, row._sa_instance_state)
