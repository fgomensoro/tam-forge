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
