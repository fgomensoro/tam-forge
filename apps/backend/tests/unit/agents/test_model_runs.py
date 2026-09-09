import json
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from tamforge_protocol.agents import AttemptTextReference


def reference(pointer="/output/draft_markdown", start=0, end=2):
    return AttemptTextReference(
        kind="attempt_text",
        attempt_id=1,
        commitment_sha256="a" * 64,
        json_pointer=pointer,
        start_codepoint=start,
        end_codepoint=end,
    )


def test_source_projection_preserves_codepoints_and_hash():
    from tamforge_backend.agents.model_runs import resolve_attempt_text

    original = json.dumps({"output": {"kind": "writing", "draft_markdown": "é🙂x"}})
    assert resolve_attempt_text(original, reference()) == sha256("é🙂".encode()).hexdigest()


@pytest.mark.parametrize(
    "pointer",
    [
        "/output/prompt",
        "/task_context/prompt",
        "/output/draft_markdown/0",
        "/output/unknown",
        "/output/key_ideas/01",
    ],
)
def test_projection_rejects_metadata_and_noncanonical_indices(pointer):
    from tamforge_backend.agents.model_runs import resolve_attempt_text

    with pytest.raises((ValueError, ValidationError)):
        resolve_attempt_text(
            json.dumps(
                {
                    "output": {
                        "kind": "writing",
                        "prompt": "xx",
                        "draft_markdown": "abc",
                        "key_ideas": ["ab", "cd"],
                    }
                }
            ),
            reference(pointer),
        )


def test_projection_rejects_range_overflow_and_wrong_output_kind():
    from tamforge_backend.agents.model_runs import resolve_attempt_text

    for original, ref in [
        ({"kind": "writing", "draft_markdown": "x"}, reference()),
        ({"kind": "sql", "draft_markdown": "abc"}, reference()),
    ]:
        with pytest.raises(ValueError):
            resolve_attempt_text(json.dumps({"output": original}), ref)


def test_lifecycle_requires_observed_resolution_and_terminal_is_final():
    from tamforge_backend.agents.contracts import Lifecycle, validate_transition

    running = Lifecycle(state="running", elapsed_ms=0, resolved_model="model-1", sdk_version="1")
    validate_transition("registered", running)
    validate_transition("running", Lifecycle(state="succeeded", elapsed_ms=12))
    with pytest.raises(ValueError):
        validate_transition("registered", Lifecycle(state="succeeded", elapsed_ms=12))
    with pytest.raises(ValueError):
        validate_transition("failed", running)
    with pytest.raises(ValidationError):
        Lifecycle(state="running", elapsed_ms=0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("arguments", {"text": "secret"}),
        ("url", "https://example.com"),
        ("credentials", "token"),
        ("tool_name", "x://password"),
    ],
)
def test_tool_contract_rejects_unrestricted_audit_fields(field, value):
    from tamforge_backend.agents.contracts import ToolAudit

    payload = dict(
        call_key="call-1",
        phase="request",
        tool_name="lookup",
        tool_version="v1",
        schema_hash="b" * 64,
        elapsed_ms=0,
        context_ordinals=(0,),
    )
    payload[field] = value
    with pytest.raises(ValidationError):
        ToolAudit(**payload)


@pytest.mark.parametrize(
    "kind,field,content,pointer",
    [
        ("reading", "key_ideas", ["one", "é🙂x"], "/output/key_ideas/1"),
        ("reading", "boundary_or_failure", "é🙂x", "/output/boundary_or_failure"),
        ("sql", "query", "é🙂x", "/output/query"),
        ("case", "discovery_questions", ["é🙂x"], "/output/discovery_questions/0"),
        ("case", "final_artifact", "é🙂x", "/output/final_artifact"),
        ("pipeline", "next_action", "é🙂x", "/output/next_action"),
    ],
)
def test_exact_learner_field_profiles(kind, field, content, pointer):
    from tamforge_backend.agents.model_runs import resolve_attempt_text

    assert (
        resolve_attempt_text(
            json.dumps({"output": {"kind": kind, field: content}}), reference(pointer)
        )
        == sha256("é🙂".encode()).hexdigest()
    )


def test_run_contract_rejects_manifest_gaps_duplicates_and_different_attempt():
    from tamforge_backend.agents.contracts import (
        ConsentBasis,
        ContextInput,
        PinnedVersion,
        RedactionDecision,
        RunRequest,
        SensitivityScope,
        SubmissionClassification,
    )

    item = ContextInput(
        ordinal=0, reason="primary_evidence", reference=reference(), prepared_input_hash="b" * 64
    )
    pin = PinnedVersion(id=1, content_hash="a" * 64)
    base = dict(
        owner_id=1,
        invocation_key="invocation-1",
        activity_id=1,
        attempt=pin,
        prompt=pin,
        schema_version=pin,
        rubric_binding=pin,
        requested_model="model",
        classification=SubmissionClassification(
            scope=SensitivityScope.RELEASABLE,
            redaction=RedactionDecision.NOT_REQUIRED,
            consent=ConsentBasis.LEARNER_SUBMISSION,
        ),
    )
    for context in [
        (),
        (item.model_copy(update={"ordinal": 1}),),
        (item, item.model_copy(update={"ordinal": 1})),
        (item.model_copy(update={"reference": reference().model_copy(update={"attempt_id": 2})}),),
    ]:
        with pytest.raises(ValidationError):
            RunRequest(**base, context=context)


@pytest.mark.parametrize(
    "event",
    [
        dict(state="failed", elapsed_ms=1),
        dict(state="succeeded", elapsed_ms=1, resolved_model="invented"),
        dict(state="running", elapsed_ms=True, resolved_model="model", cli_version="1"),
        dict(
            state="cancelled",
            elapsed_ms=1,
            error_category="cancelled",
            retry_disposition="retryable",
        ),
    ],
)
def test_lifecycle_closed_contract_rejects_incoherent_observations(event):
    from tamforge_backend.agents.contracts import Lifecycle

    with pytest.raises(ValidationError):
        Lifecycle(**event)


def run_request(**overrides):
    from tamforge_backend.agents.contracts import (
        ConsentBasis,
        ContextInput,
        PinnedVersion,
        RedactionDecision,
        RunRequest,
        SensitivityScope,
        SubmissionClassification,
    )

    pin = PinnedVersion(id=1, content_hash="a" * 64)
    fields = dict(
        owner_id=1,
        invocation_key="invocation-1",
        activity_id=1,
        attempt=pin,
        prompt=pin,
        schema_version=pin,
        rubric_binding=pin,
        requested_model="model",
        context=(
            ContextInput(
                ordinal=0,
                reason="primary_evidence",
                reference=reference(),
                prepared_input_hash=sha256(b"ab").hexdigest(),
            ),
        ),
        classification=SubmissionClassification(
            scope=SensitivityScope.RELEASABLE,
            redaction=RedactionDecision.NOT_REQUIRED,
            consent=ConsentBasis.LEARNER_SUBMISSION,
        ),
    )
    return RunRequest(**dict(fields, **overrides))


@pytest.mark.parametrize("replayed,outcome", [(False, "succeeded"), (True, "noop")])
def test_accepted_submission_audit_records_whether_it_was_a_replay(replayed, outcome):
    from tamforge_backend.agents.model_runs import ModelRunRepository
    from tamforge_backend.auth.audit import AuditReasonCode

    class Session:
        def __init__(self):
            self.added = []

        def add(self, row):
            self.added.append(row)

    request = run_request(activity_id=9)
    session = Session()

    ModelRunRepository(session)._audit(request, reason=AuditReasonCode.NONE, replayed=replayed)

    event = session.added[0]
    assert event.action == "model_run.submitted"
    assert event.aggregate_id == "9"
    # A replay carries the original's correlation hash, so only the metadata tells them apart.
    assert event.idempotency_correlation_hash == sha256(b"invocation-1").digest()
    assert event.redacted_metadata["outcome"] == outcome
    assert event.redacted_metadata["flags"]["replayed"] is replayed
    assert event.redacted_metadata["flags"]["authorized"] is True


def test_conflicting_resubmission_is_refused_with_a_conflict_audit_record():
    """Reusing an invocation key with different content is a refused submission.

    It is also what replay tampering looks like, so it belongs in the trail even
    though the transaction that detected it is rolled back.
    """
    import asyncio
    from contextlib import asynccontextmanager

    from tamforge_backend.agents.contracts import ImmutableVersionConflict
    from tamforge_backend.agents.model_runs import ModelRunRepository
    from tamforge_backend.agents.models import ModelRun

    attempt_text = json.dumps({"output": {"kind": "writing", "draft_markdown": "abc"}})
    stored = '{"kind":"a different run"}'

    class Session:
        def __init__(self):
            self.rows = []

        @asynccontextmanager
        async def begin(self):
            # Model the rollback, so this test fails if the audit is ever moved
            # inside the block the refusal discards.
            committed = len(self.rows)
            try:
                yield self
            except BaseException:
                del self.rows[committed:]
                raise

        async def scalar(self, statement):
            source = str(statement)
            if "FROM attempts" in source:
                return SimpleNamespace(
                    original_text=attempt_text,
                    commitment_hash=bytes.fromhex("a" * 64),
                    attempt_kind="practice",
                )
            if "FROM model_runs" in source:
                return ModelRun(
                    owner_id=1,
                    canonical_json=stored,
                    content_hash=sha256(stored.encode()).digest(),
                    hash_format=1,
                )
            return 1

        def add(self, row):
            self.rows.append(row)

    async def exercise():
        session = Session()
        with pytest.raises(ImmutableVersionConflict):
            await ModelRunRepository(session).register(run_request())
        assert len(session.rows) == 1
        event = session.rows[0]
        assert event.action == "model_run.refused"
        assert event.aggregate_id == "1"
        assert event.idempotency_correlation_hash == sha256(b"invocation-1").digest()
        assert event.redacted_metadata["outcome"] == "denied"
        assert event.redacted_metadata["reason_code"] == "conflict"
        assert event.redacted_metadata["flags"]["authorized"] is False
        # Every path emits the flag, so a reader never reads an absent one as false.
        assert event.redacted_metadata["flags"]["replayed"] is False

    asyncio.run(exercise())
