"""Sensitivity derived from artifact class, and the submissions it permits.

A scope is a function of the artifact's class rather than a stored column, so every
artifact carries one the moment this rule exists, including rows written before it.
"""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import ConsentBasis as ConsentBasis
from .contracts import RedactionDecision as RedactionDecision
from .contracts import SensitivityScope, SubmissionClassification

# Ordered least to most restrictive. Position is the comparison.
_ORDER = (
    SensitivityScope.RELEASABLE,
    SensitivityScope.REDACTION_REQUIRED,
    SensitivityScope.RESTRICTED,
)

SCOPE_BY_ARTIFACT_CLASS = {
    "original_audio": SensitivityScope.RESTRICTED,
    "export": SensitivityScope.RESTRICTED,
    "transcript": SensitivityScope.REDACTION_REQUIRED,
    "written_output": SensitivityScope.RELEASABLE,
    "sql_output": SensitivityScope.RELEASABLE,
    "case_artifact": SensitivityScope.RELEASABLE,
    "recall_note": SensitivityScope.RELEASABLE,
    "analysis": SensitivityScope.RELEASABLE,
}


def scope_of(artifact_class: str) -> SensitivityScope:
    """An unrecognised class is restricted. A new class must be classified to be sent."""
    return SCOPE_BY_ARTIFACT_CLASS.get(artifact_class, SensitivityScope.RESTRICTED)


def most_restrictive(scopes: Iterable[SensitivityScope]) -> SensitivityScope:
    return max(scopes, key=_ORDER.index, default=SensitivityScope.RELEASABLE)


def derive_submission_scope(
    *, attempt_kind: str, cited_artifact_classes: Iterable[str] = ()
) -> SensitivityScope:
    """The sensitivity of what the submission sends, not of everything stored beside it.

    The prepared text comes from the attempt's own committed output. Linked artifacts are
    evidence kept alongside it and are not part of that text, so deriving from everything
    linked would make any recorded session permanently unsendable: original_audio is
    restricted, and a restricted scope cannot be declared at all.

    A real interview carries a second person's words, so its text needs an approved
    redaction and an explicit release before it goes anywhere.
    """
    scopes = [scope_of(item) for item in cited_artifact_classes]
    scopes.append(
        SensitivityScope.REDACTION_REQUIRED
        if attempt_kind == "real_interview"
        else SensitivityScope.RELEASABLE
    )
    return most_restrictive(scopes)


def understates(declared: SubmissionClassification, derived: SensitivityScope) -> bool:
    return _ORDER.index(declared.scope) < _ORDER.index(derived)
