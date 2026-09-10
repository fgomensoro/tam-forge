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


class RecordingSession(FakeSession):
    def __init__(self, row=None):
        super().__init__(row)
        self.added = []

    def add(self, instance):
        self.added.append(instance)


def current_record():
    from tamforge_backend.agents.settings import EXPECTED_POLICY_VERSION, AttestationRecord

    return AttestationRecord.model_validate(
        {
            "policy_version": EXPECTED_POLICY_VERSION,
            "model_improvement_disabled": True,
            "subscription_policy_acknowledged": True,
        }
    )


def test_recording_writes_the_exact_canonical_bytes_the_table_demands():
    from tamforge_backend.agents.compatibility import AttestationRepository
    from tamforge_backend.agents.hashing import canonical_bytes

    session = RecordingSession()
    asyncio.run(AttestationRepository(session).record(owner_id=1, record=current_record()))
    assert len(session.added) == 1
    row = session.added[0]
    expected = canonical_bytes(current_record().model_dump(mode="json"))
    assert row.canonical_json.encode() == expected
    assert row.content_hash == sha256(expected).digest()
    assert row.owner_id == 1


def test_re_attesting_to_the_same_policy_writes_nothing_new():
    from tamforge_backend.agents.compatibility import AttestationRepository
    from tamforge_backend.agents.hashing import canonical_bytes

    payload = canonical_bytes(current_record().model_dump(mode="json")).decode()
    session = RecordingSession(FakeRow(payload))
    asyncio.run(AttestationRepository(session).record(owner_id=1, record=current_record()))
    assert session.added == []


def test_a_stored_row_that_disagrees_with_the_same_policy_version_conflicts():
    from tamforge_backend.agents.compatibility import AttestationRepository
    from tamforge_backend.agents.contracts import ImmutableVersionConflict
    from tamforge_backend.agents.settings import EXPECTED_POLICY_VERSION

    tampered = FakeRow(
        json.dumps(
            {
                "model_improvement_disabled": True,
                "policy_version": EXPECTED_POLICY_VERSION,
                "subscription_policy_acknowledged": True,
                "extra": "not what we would write",
            }
        )
    )
    with pytest.raises(ImmutableVersionConflict):
        asyncio.run(
            AttestationRepository(RecordingSession(tampered)).record(
                owner_id=1, record=current_record()
            )
        )


def test_recording_rejects_an_invalid_owner():
    from tamforge_backend.agents.compatibility import AttestationRepository
    from tamforge_backend.agents.contracts import InvalidProvenance

    for owner in (0, -1, True, "1"):
        with pytest.raises(InvalidProvenance):
            asyncio.run(
                AttestationRepository(RecordingSession()).record(
                    owner_id=owner, record=current_record()
                )
            )


def test_the_recorded_bytes_read_back_as_the_same_attestation():
    """Writer and reader agree, so an attestation recorded here opens the gate."""
    from tamforge_backend.agents.compatibility import AttestationRepository
    from tamforge_backend.agents.settings import attestation_is_current

    session = RecordingSession()
    asyncio.run(AttestationRepository(session).record(owner_id=1, record=current_record()))
    written = session.added[0]
    read_back = read(FakeRow(written.canonical_json))
    assert read_back is not None
    assert attestation_is_current(read_back) is True


class StubRuntime:
    """A fake Agent SDK runtime. Records what the probe asked it, and nothing else."""

    def __init__(self, observation=None, error=None):
        self.observation = observation
        self.error = error
        self.calls = []

    async def probe(self, *, requested_model: str):
        self.calls.append({"requested_model": requested_model})
        if self.error is not None:
            raise self.error
        return self.observation


def observation(**overrides):
    from tamforge_backend.agents.compatibility import EXPECTED_STRUCTURED_RESPONSE, ProbeObservation

    data = {
        "sdk_version": "1.4.2",
        "cli_version": "2.0.9",
        "authentication_method": "subscription",
        "resolved_model": "claude-sonnet-5-20260101",
        "supported_models": ("claude-sonnet-5-20260101", "claude-opus-5-20260101"),
        "structured_response": dict(EXPECTED_STRUCTURED_RESPONSE),
    }
    data.update(overrides)
    return ProbeObservation(**data)


NOW = __import__("datetime").datetime(2026, 9, 10, 12, 0, tzinfo=__import__("datetime").UTC)


def run_probe(runtime, *, enabled=True, record="current", requested_model="claude-sonnet-5"):
    from tamforge_backend.agents.compatibility import probe_claude_compatibility

    stored = {
        None: None,
        "stale": lambda: attestation(policy_version="superseded-v0"),
        "current": attestation,
    }[record]
    return asyncio.run(
        probe_claude_compatibility(
            runtime=runtime,
            repository=StubRepository(stored() if callable(stored) else stored),
            owner_id=1,
            enabled=enabled,
            requested_model=requested_model,
            now=NOW,
        )
    )


def test_a_compatible_runtime_is_ready_and_reports_what_it_resolved():
    runtime = StubRuntime(observation())
    result = run_probe(runtime)

    assert (result.status, result.reason) == ("ready", "none")
    assert result.claude_may_run is True
    assert result.resolved_model == "claude-sonnet-5-20260101"
    assert result.sdk_version == "1.4.2"
    assert result.cli_version == "2.0.9"
    assert result.checked_at == NOW
    assert runtime.calls == [{"requested_model": "claude-sonnet-5"}]


@pytest.mark.parametrize(
    "enabled,record,reason",
    [
        (False, "current", "not_enabled"),
        (True, None, "attestation_missing"),
        (True, "stale", "attestation_superseded"),
    ],
)
def test_the_gate_runs_before_the_probe_and_never_calls_the_runtime(enabled, record, reason):
    runtime = StubRuntime(observation())
    result = run_probe(runtime, enabled=enabled, record=record)

    assert (result.status, result.reason) == ("disabled", reason)
    assert result.claude_may_run is False
    assert runtime.calls == []


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"sdk_version": None}, "sdk_not_installed"),
        ({"sdk_version": "0.0.9"}, "sdk_version_unsupported"),
        ({"authentication_method": "none"}, "authentication_missing"),
        ({"authentication_method": "api_key"}, "authentication_not_subscription"),
        ({"authentication_method": "bedrock"}, "authentication_not_subscription"),
        ({"resolved_model": None}, "model_unavailable"),
        ({"resolved_model": "claude-retired-1"}, "model_unavailable"),
        ({"structured_response": {"probe": "ok"}}, "structured_output_unsupported"),
        ({"structured_response": None}, "structured_output_unsupported"),
    ],
)
def test_an_incompatible_runtime_blocks_claude_work_with_an_actionable_reason(overrides, reason):
    result = run_probe(StubRuntime(observation(**overrides)))

    assert (result.status, result.reason) == ("blocked", reason)
    assert result.claude_may_run is False
    assert result.remediation


def test_a_supported_model_that_is_not_the_resolved_one_still_fails():
    # The subscription lists a model the runtime did not resolve to; only the
    # resolved identifier decides, because that is what a job would actually run.
    result = run_probe(
        StubRuntime(
            observation(
                resolved_model="claude-sonnet-4-20250101",
                supported_models=("claude-sonnet-5-20260101",),
            )
        )
    )

    assert result.reason == "model_unavailable"


@pytest.mark.parametrize(
    "error_name,status,reason",
    [
        ("ProbeQuotaExhausted", "needs_attention", "quota_exhausted"),
        ("ProbeAuthenticationFailed", "blocked", "authentication_rejected"),
        ("ProbePolicyRejected", "blocked", "policy_rejected"),
    ],
)
def test_probe_failures_are_classified_not_propagated(error_name, status, reason):
    from tamforge_backend.agents import compatibility

    error = getattr(compatibility, error_name)("stop")
    result = run_probe(StubRuntime(error=error))

    assert (result.status, result.reason) == (status, reason)
    assert result.claude_may_run is False
    assert result.remediation


def test_an_unexpected_runtime_failure_never_leaks_its_message():
    secret = "sk-ant-oat01-do-not-log"
    result = run_probe(StubRuntime(error=RuntimeError(secret)))

    assert (result.status, result.reason) == ("needs_attention", "probe_failed")
    assert secret not in json.dumps(
        {
            "status": result.status,
            "reason": result.reason,
            "remediation": result.remediation,
            "resolved_model": result.resolved_model,
            "sdk_version": result.sdk_version,
            "cli_version": result.cli_version,
        }
    )


def test_every_reason_has_its_own_remediation():
    from tamforge_backend.agents.compatibility import PROBE_REASONS, PROBE_REMEDIATION

    assert set(PROBE_REMEDIATION) == set(PROBE_REASONS)
    assert all(text.strip() for text in PROBE_REMEDIATION.values())


def test_the_probe_sends_no_owner_content():
    runtime = StubRuntime(observation())
    run_probe(runtime)

    sent = json.dumps(runtime.calls)
    assert "owner" not in sent and "attempt" not in sent and "transcript" not in sent
    assert list(runtime.calls[0]) == ["requested_model"]
