"""Derived sensitivity and the submission combinations that must never exist."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_every_artifact_class_has_a_scope():
    from tamforge_backend.agents.classification import SCOPE_BY_ARTIFACT_CLASS
    from tamforge_backend.learning.models import Artifact

    allowed = next(
        constraint.sqltext.text
        for constraint in Artifact.__table__.constraints
        # The table's naming_convention prefixes bound check constraints with
        # "ck_<table>_", so match on the declared suffix rather than the raw name.
        if (getattr(constraint, "name", None) or "").endswith("artifact_class_allowed")
    )
    classes = set(__import__("re").findall(r"'([a-z_]+)'", allowed))
    assert classes == set(SCOPE_BY_ARTIFACT_CLASS)


@pytest.mark.parametrize(
    "artifact_class,scope",
    [
        ("original_audio", "restricted"),
        ("export", "restricted"),
        ("transcript", "redaction_required"),
        ("written_output", "releasable"),
        ("sql_output", "releasable"),
        ("case_artifact", "releasable"),
        ("recall_note", "releasable"),
        ("analysis", "releasable"),
    ],
)
def test_scope_of_known_classes(artifact_class, scope):
    from tamforge_backend.agents.classification import scope_of
    from tamforge_backend.agents.contracts import SensitivityScope

    assert scope_of(artifact_class) is SensitivityScope(scope)


def test_an_unknown_class_is_restricted_rather_than_releasable():
    from tamforge_backend.agents.classification import scope_of
    from tamforge_backend.agents.contracts import SensitivityScope

    assert scope_of("something_new") is SensitivityScope.RESTRICTED


def test_most_restrictive_wins():
    from tamforge_backend.agents.classification import most_restrictive
    from tamforge_backend.agents.contracts import SensitivityScope

    assert most_restrictive([]) is SensitivityScope.RELEASABLE
    assert (
        most_restrictive([SensitivityScope.RELEASABLE, SensitivityScope.REDACTION_REQUIRED])
        is SensitivityScope.REDACTION_REQUIRED
    )
    assert (
        most_restrictive([SensitivityScope.REDACTION_REQUIRED, SensitivityScope.RESTRICTED])
        is SensitivityScope.RESTRICTED
    )


def releasable(**overrides):
    data = {
        "scope": "releasable",
        "redaction": "not_required",
        "consent": "learner_submission",
    }
    data.update(overrides)
    return data


def test_a_releasable_learner_submission_is_accepted():
    from tamforge_backend.agents.contracts import SubmissionClassification

    assert SubmissionClassification.model_validate(releasable()).scope.value == "releasable"


def test_restricted_content_is_never_submittable():
    from tamforge_backend.agents.contracts import SubmissionClassification

    for extra in ({}, {"redaction": "approved", "consent": "explicit_release"}):
        with pytest.raises(ValidationError):
            SubmissionClassification.model_validate(releasable(scope="restricted", **extra))


def test_redaction_required_needs_both_approval_and_explicit_release():
    from tamforge_backend.agents.contracts import SubmissionClassification

    for redaction, consent in [
        ("not_required", "explicit_release"),
        ("pending", "explicit_release"),
        ("approved", "learner_submission"),
    ]:
        with pytest.raises(ValidationError):
            SubmissionClassification.model_validate(
                releasable(scope="redaction_required", redaction=redaction, consent=consent)
            )
    SubmissionClassification.model_validate(
        releasable(scope="redaction_required", redaction="approved", consent="explicit_release")
    )


def test_withheld_consent_is_never_submittable():
    from tamforge_backend.agents.contracts import SubmissionClassification

    with pytest.raises(ValidationError):
        SubmissionClassification.model_validate(releasable(consent="not_granted"))


def test_a_releasable_scope_cannot_claim_a_redaction_it_did_not_need():
    from tamforge_backend.agents.contracts import SubmissionClassification

    for redaction in ("pending", "approved"):
        with pytest.raises(ValidationError):
            SubmissionClassification.model_validate(releasable(redaction=redaction))


def test_run_request_requires_a_classification():
    from tamforge_backend.agents.contracts import RunRequest, SubmissionClassification

    # Asserting the field itself, because a payload missing everything raises whether or
    # not this one field is required, and would pass if the field were dropped entirely.
    field = RunRequest.model_fields["classification"]
    assert field.is_required()
    assert field.annotation is SubmissionClassification


def test_derived_scope_is_the_most_restrictive_cited_class():
    from tamforge_backend.agents.classification import SensitivityScope, derive_submission_scope

    assert derive_submission_scope([]) is SensitivityScope.RELEASABLE
    assert derive_submission_scope(["written_output"]) is SensitivityScope.RELEASABLE
    assert (
        derive_submission_scope(["written_output", "transcript"])
        is SensitivityScope.REDACTION_REQUIRED
    )
    assert (
        derive_submission_scope(["written_output", "original_audio"])
        is SensitivityScope.RESTRICTED
    )


def test_a_declared_scope_may_not_understate_the_derived_one():
    from tamforge_backend.agents.classification import (
        ConsentBasis,
        RedactionDecision,
        SensitivityScope,
        SubmissionClassification,
        understates,
    )

    declared = SubmissionClassification(
        scope=SensitivityScope.RELEASABLE,
        redaction=RedactionDecision.NOT_REQUIRED,
        consent=ConsentBasis.LEARNER_SUBMISSION,
    )
    assert understates(declared, SensitivityScope.RELEASABLE) is False
    assert understates(declared, SensitivityScope.REDACTION_REQUIRED) is True
    assert understates(declared, SensitivityScope.RESTRICTED) is True
