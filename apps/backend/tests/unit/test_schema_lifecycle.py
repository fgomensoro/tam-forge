from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_mock_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


@pytest.mark.parametrize("operation", ["create_all", "drop_all"])
def test_metadata_schema_lifecycle_is_alembic_only_without_partial_ddl(operation: str) -> None:
    from tamforge_backend.models import Base, load_all_models
    from tamforge_backend.models.base import SchemaLifecycleError

    load_all_models()
    emitted: list[str] = []
    engine = create_mock_engine(
        "postgresql+psycopg://",
        lambda statement, *args, **kwargs: emitted.append(str(statement)),
    )

    with pytest.raises(SchemaLifecycleError, match="Alembic"):
        getattr(Base.metadata, operation)(engine)

    assert emitted == []


def test_metadata_ddl_introspection_still_compiles_without_execution() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    compiled = {
        table.name: str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for table in Base.metadata.sorted_tables
    }

    assert "CREATE TABLE owners" in compiled["owners"]
    assert "CREATE TABLE audit_events" in compiled["audit_events"]
    assert "NULL}'" not in compiled["audit_events"]
    assert "%(" not in compiled["audit_events"]
    assert "redacted_metadata JSONB NOT NULL" in compiled["audit_events"]
    assert "redacted_metadata JSONB DEFAULT" not in compiled["audit_events"]
    assert "result_payload JSONB DEFAULT '{}'::jsonb NOT NULL" in compiled[
        "command_receipts"
    ]


@pytest.mark.parametrize("operation", ["create_all", "drop_all"])
def test_metadata_guard_is_import_order_independent_in_a_fresh_process(operation: str) -> None:
    source = (
        "from sqlalchemy import create_mock_engine; "
        "from tamforge_backend.models.base import Base, SchemaLifecycleError; "
        "from tamforge_backend.models import load_all_models; "
        "load_all_models(); emitted=[]; "
        "engine=create_mock_engine('postgresql+psycopg://', "
        "lambda statement,*args,**kwargs: emitted.append(str(statement))); "
        "\ntry:\n"
        f" Base.metadata.{operation}(engine)\n"
        "except SchemaLifecycleError:\n"
        " assert emitted == []\n"
        "else:\n"
        " raise AssertionError('schema lifecycle guard did not run')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
