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


def test_shared_fixture_rejects_public_schema_drift() -> None:
    fixture = deepcopy(load_fixture())
    fixture["responses"]["today"]["unexpected"] = True

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_fixture(fixture)
