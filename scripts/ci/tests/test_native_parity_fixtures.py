from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.ci.check_native_parity_fixtures import (
    FixtureError,
    load_fixture,
    validate_fixture,
)


def test_shared_native_parity_fixture_matches_source_and_backend_contracts() -> None:
    validate_fixture(load_fixture())


def test_shared_fixture_rejects_source_package_drift() -> None:
    fixture = load_fixture()
    fixture["source_package"]["sha256"] = "0" * 64

    with pytest.raises(FixtureError, match="digest drifted"):
        validate_fixture(fixture)


def test_shared_fixture_rejects_cross_response_relationship_drift() -> None:
    fixture = deepcopy(load_fixture())
    fixture["responses"]["activity"]["id"] = 99

    with pytest.raises(FixtureError, match="Today/activity relationship"):
        validate_fixture(fixture)


def test_shared_fixture_rejects_real_roadmap_projection_drift() -> None:
    fixture = deepcopy(load_fixture())
    fixture["responses"]["roadmap_version"]["version_key"] = "month-1-v1"

    with pytest.raises(FixtureError, match="roadmap projection"):
        validate_fixture(fixture)


def test_shared_fixture_rejects_impossible_portfolio_evidence() -> None:
    fixture = deepcopy(load_fixture())
    fixture["responses"]["portfolio"]["items"] = [
        {
            "id": 91,
            "activity_id": 41,
            "attempt_id": 11,
            "formula_version": "seed-v1",
            "rubric_version": "seed-v1",
            "total_score": "14.000",
            "components": [],
            "trend_basis": {
                "schema_version": 1,
                "basis_code": "first_score",
                "event_ids": [],
            },
            "scored_at": "2026-08-24T20:00:00Z",
        }
    ]

    with pytest.raises(FixtureError, match="portfolio relationship"):
        validate_fixture(fixture)


def test_shared_fixture_rejects_public_schema_drift() -> None:
    fixture = deepcopy(load_fixture())
    fixture["responses"]["today"]["unexpected"] = True

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_fixture(fixture)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("estimated_level",), "2.411"),
        (("confidence_basis", "basis_code"), "high_weight"),
        (("manifest", 0, "event_id"), 999),
    ],
)
def test_shared_fixture_rejects_assessed_skill_business_or_lineage_drift(
    path: tuple[object, ...], value: object
) -> None:
    fixture = deepcopy(load_fixture())
    target = fixture["responses"]["skills"]["items"][0]["latest_snapshot"]
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value

    with pytest.raises(FixtureError, match="assessed skill lineage"):
        validate_fixture(fixture)
