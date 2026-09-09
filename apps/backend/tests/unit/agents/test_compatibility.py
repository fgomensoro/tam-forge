"""Status derived from what is stored, with no database in the unit path."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256

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


class FakeSession:
    """Just enough AsyncSession for the reader: a scalar result and a no-op transaction."""

    def __init__(self, row):
        self.row = row

    def begin(self):
        session = self

        class Transaction:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        return Transaction()

    async def scalar(self, statement):
        del statement
        return self.row


class FakeRow:
    def __init__(self, canonical_json):
        self.canonical_json = canonical_json
        self.hash_format = 1
        self.content_hash = sha256(canonical_json.encode()).digest()


def stored(payload):
    return FakeRow(json.dumps(payload))


def read(row):
    from tamforge_backend.agents.compatibility import AttestationRepository

    return asyncio.run(AttestationRepository(FakeSession(row)).current(owner_id=1))


def test_a_stored_attestation_is_read_back():
    from tamforge_backend.agents.settings import EXPECTED_POLICY_VERSION

    record = read(
        stored(
            {
                "policy_version": EXPECTED_POLICY_VERSION,
                "model_improvement_disabled": True,
                "subscription_policy_acknowledged": True,
            }
        )
    )
    assert record is not None
    assert record.policy_version == EXPECTED_POLICY_VERSION


def test_no_row_is_no_attestation():
    assert read(None) is None


@pytest.mark.parametrize(
    "payload",
    [
        "not json at all",
        '{"policy_version": "x"}',
        '{"policy_version": "x", "model_improvement_disabled": false,'
        ' "subscription_policy_acknowledged": true}',
    ],
)
def test_a_broken_attestation_is_not_consent(payload):
    """Unparsable, incomplete, or negative rows read as no attestation, never as permission."""
    assert read(FakeRow(payload)) is None


def test_a_row_whose_hash_does_not_match_is_rejected():
    from tamforge_backend.agents.contracts import InvalidProvenance

    row = stored(
        {
            "policy_version": "x",
            "model_improvement_disabled": True,
            "subscription_policy_acknowledged": True,
        }
    )
    row.content_hash = b"\x00" * 32
    with pytest.raises(InvalidProvenance):
        read(row)


def test_an_invalid_owner_is_rejected_before_any_query():
    from tamforge_backend.agents.compatibility import AttestationRepository
    from tamforge_backend.agents.contracts import InvalidProvenance

    for owner in (0, -1, True, "1"):
        with pytest.raises(InvalidProvenance):
            asyncio.run(AttestationRepository(FakeSession(None)).current(owner_id=owner))
