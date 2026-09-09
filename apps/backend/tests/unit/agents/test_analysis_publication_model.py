"""Table shape and immutability wiring for published analyses."""

from __future__ import annotations

import pytest


def test_publication_is_registered_as_immutable_provenance():
    from tamforge_backend.agents.models import RECORD_TYPES, AnalysisPublication

    assert AnalysisPublication in RECORD_TYPES


def test_publication_is_one_row_per_run_and_kind():
    from tamforge_backend.agents.models import AnalysisPublication

    table = AnalysisPublication.__table__
    assert table.name == "analysis_publications"
    unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("run_id", "analysis_kind") in unique


def test_publication_rejects_mutation():
    from tamforge_backend.agents.contracts import ImmutableVersionConflict
    from tamforge_backend.agents.models import reject_mutation

    with pytest.raises(ImmutableVersionConflict):
        reject_mutation()


def test_migration_creates_the_table_and_its_immutability_trigger():
    from pathlib import Path

    root = Path(__file__).resolve().parents[5]
    source = (
        root / "apps/backend/alembic/versions/20260908_0016_publications.py"
    ).read_text()
    assert "CREATE TABLE analysis_publications" in source
    assert "trg_analysis_publications_immutable" in source
    assert 'down_revision = "20260905_0015_model_provenance"' in source
