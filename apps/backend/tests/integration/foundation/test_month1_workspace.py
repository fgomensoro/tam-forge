"""Complete Month 1 foundation journey through real application boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

import boto3
import httpx
import pytest
import respx
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"
PARITY_FIXTURE = (
    ROOT / "tests" / "fixtures" / "native-parity" / "foundation-journey-v1.json"
)
ACTIVITY_RESPONSE_FIELDS = (
    "id",
    "study_day_id",
    "state",
    "optimistic_version",
    "classification",
    "stronger_evidence_id",
    "activity_focused_seconds",
    "day_focused_minutes",
    "hard_stop_recommended",
    "open_timer",
    "source_hidden",
)
TODAY_VOLATILE_FIELDS = frozenset(
    {"source_updated_at", "read_model_version", "etag"}
)


def _without_fields(
    payload: dict[str, object], fields: frozenset[str]
) -> dict[str, object]:
    missing = fields.difference(payload)
    assert not missing, f"volatile response fields disappeared: {sorted(missing)}"
    return {key: value for key, value in payload.items() if key not in fields}


def _isolated_object_store() -> dict[str, str]:
    expected = {
        "TAMFORGE_OBJECT_STORE_ENDPOINT": "http://127.0.0.1:9000",
        "TAMFORGE_OBJECT_STORE_BUCKET": "tam-forge-parity-test",
        "TAMFORGE_OBJECT_STORE_ACCESS_KEY": "tamforge",
        "TAMFORGE_OBJECT_STORE_SECRET_KEY": "tamforge-local",
    }
    configured = {name: os.getenv(name) for name in expected}
    if all(value is None for value in configured.values()):
        pytest.skip("isolated MinIO settings are required; tests never autostart Docker")
    mismatched = [
        name for name, expected_value in expected.items() if configured[name] != expected_value
    ]
    if mismatched:
        pytest.fail(
            "isolated MinIO settings must match the locked parity target: "
            + ", ".join(mismatched),
            pytrace=False,
        )
    return expected


@respx.mock
def test_month1_workspace_is_authenticated_resumable_and_idempotent(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.auth.models import CommandReceipt
    from tamforge_backend.auth.service import AuthService
    from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
    from tamforge_backend.database import (
        database_url_to_sync,
        transaction_scope,
        validate_test_database_url,
    )
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.evidence.models import RubricEvaluation, SkillEvidenceEvent
    from tamforge_backend.evidence.repository import SqlAlchemyEvidenceRepository
    from tamforge_backend.evidence.schemas import (
        DimensionEvaluationInput,
        EvidenceEvaluationCommand,
        SkillDimensionSubsetInput,
    )
    from tamforge_backend.evidence.seed import seed_config
    from tamforge_backend.evidence.service import EvidenceService
    from tamforge_backend.learning.models import ActivityInstance, Attempt, SelfReview
    from tamforge_backend.main import create_app
    from tamforge_backend.notifications.models import Notification, OutboxEvent
    from tamforge_backend.notifications.repository import SqlAlchemyNotificationRepository
    from tamforge_backend.roadmaps.contracts import ParsedRoadmap
    from tamforge_backend.roadmaps.diff import diff_roadmaps
    from tamforge_backend.roadmaps.models import RoadmapImport
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.parser import parse_roadmap
    from tamforge_backend.storage.s3 import S3ObjectStore
    from tamforge_backend.today.repository import SqlAlchemyTodayRepository
    from tamforge_backend.today.service import TodayService

    object_store = _isolated_object_store()
    package_bytes = FIXTURE.read_bytes()
    parity = json.loads(PARITY_FIXTURE.read_text(encoding="utf-8"))
    assert parity["source_package"] == {
        "path": "apps/backend/tests/fixtures/roadmaps/month-v1.zip",
        "sha256": hashlib.sha256(package_bytes).hexdigest(),
        "byte_length": len(package_bytes),
    }
    validated_database_url = validate_test_database_url(test_database_url)
    database_target = make_url(validated_database_url)
    if (
        database_target.host != "127.0.0.1"
        or database_target.port != 54329
        or database_target.database != "tamforge_test"
        or bool(database_target.query)
    ):
        pytest.fail(
            "durable parity requires exactly "
            "127.0.0.1:54329/tamforge_test without URL query parameters",
            pytrace=False,
        )
    test_database_url = validated_database_url
    bundle = load_config_bundle(ROOT / "config")
    with inspect_zip_stream((package_bytes,)) as inspected_package:
        assert inspected_package.accepted
        expected_roadmap = parse_roadmap(
            files={
                item.manifest.path: item.staged_path.read_bytes()
                for item in inspected_package.files
            },
            config=bundle,
        )
    empty_roadmap = ParsedRoadmap(
        schema_version=expected_roadmap.schema_version,
        roadmap_version=expected_roadmap.roadmap_version,
        tasks=(),
        contracts=(),
        resources=(),
        exit_criteria=(),
        normalized_hash="0" * 64,
    )
    expected_import_response = {
        "status": "validated",
        "validation_report": {
            "schema_version": 1,
            "accepted": True,
            "normalized_hash": expected_roadmap.normalized_hash,
            "task_count": len(expected_roadmap.tasks),
            "resource_count": len(expected_roadmap.resources),
            "exit_criterion_count": len(expected_roadmap.exit_criteria),
            "issues": [],
        },
        "semantic_diff": diff_roadmaps(empty_roadmap, expected_roadmap).to_dict(),
        "failure_code": None,
    }
    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    s3_client = boto3.client(
        "s3",
        endpoint_url=object_store["TAMFORGE_OBJECT_STORE_ENDPOINT"],
        region_name="us-east-1",
        aws_access_key_id=object_store["TAMFORGE_OBJECT_STORE_ACCESS_KEY"],
        aws_secret_access_key=object_store["TAMFORGE_OBJECT_STORE_SECRET_KEY"],
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    try:
        try:
            s3_client.head_bucket(Bucket=object_store["TAMFORGE_OBJECT_STORE_BUCKET"])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {
                "404",
                "NoSuchBucket",
                "NotFound",
            }:
                raise
            s3_client.create_bucket(Bucket=object_store["TAMFORGE_OBJECT_STORE_BUCKET"])
        command.downgrade(migration, "base")
        command.upgrade(migration, "head")

        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")

        async def exercise() -> None:
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            settings = Settings(
                environment="test",
                database_url=async_url.render_as_string(hide_password=False),
                github_user_id=APPROVED_GITHUB_USER_ID,
                github_client_id="client-id",
                github_client_secret="provider-secret-not-persisted",
                session_signing_secret="state-signing-secret-with-enough-entropy",
                github_callback_url="https://app.example.test/api/v1/auth/callback",
                cors_origins=["https://app.example.test"],
                secure_cookies=False,
                roadmap_config_dir=ROOT / "config",
                object_store_endpoint=object_store["TAMFORGE_OBJECT_STORE_ENDPOINT"],
                object_store_bucket=object_store["TAMFORGE_OBJECT_STORE_BUCKET"],
                object_store_access_key=object_store[
                    "TAMFORGE_OBJECT_STORE_ACCESS_KEY"
                ],
                object_store_secret_key=object_store[
                    "TAMFORGE_OBJECT_STORE_SECRET_KEY"
                ],
                object_store_region="us-east-1",
                object_store_addressing_style="path",
                github_roadmap_mirror_token="",
                github_roadmap_mirror_repository="",
                _env_file=None,
            )
            app = create_app(settings)
            assert app.dependency_overrides == {}
            transport = ASGITransport(app=app)

            async def mutate(
                client: AsyncClient,
                path: str,
                body: dict[str, object],
                key: str,
            ) -> httpx.Response:
                return await client.post(
                    path,
                    json=body,
                    headers={**native_headers, "Idempotency-Key": key},
                )

            async def assert_activity_response(
                client: AsyncClient,
                response: httpx.Response,
                *,
                activity_path: str,
                expected_state: str,
                expected_version: int,
                expected_source_hidden: bool,
                timer_open: bool,
            ) -> dict[str, object]:
                assert response.status_code == 200, response.text
                payload = cast(dict[str, object], response.json())
                detail_response = await client.get(
                    activity_path,
                    headers=native_headers,
                )
                assert detail_response.status_code == 200, detail_response.text
                detail_payload = detail_response.json()
                assert payload == {
                    key: detail_payload[key] for key in ACTIVITY_RESPONSE_FIELDS
                }
                assert payload["state"] == expected_state
                assert payload["optimistic_version"] == expected_version
                assert payload["source_hidden"] is expected_source_hidden
                assert (payload["open_timer"] is not None) is timer_open
                return payload

            try:
                async with app.router.lifespan_context(app):
                    respx.post("https://github.com/login/oauth/access_token").mock(
                        return_value=httpx.Response(
                            200,
                            json={
                                "access_token": "provider-access-token",
                                "token_type": "bearer",
                            },
                        )
                    )
                    respx.get("https://api.github.com/user").mock(
                        return_value=httpx.Response(
                            200,
                            json={
                                "id": APPROVED_GITHUB_USER_ID,
                                "login": "fgomensoro",
                            },
                        )
                    )
                    verifier = "v" * 43
                    challenge = AuthService.pkce_challenge(verifier)
                    async with AsyncClient(
                        transport=transport,
                        base_url="https://app.example.test",
                    ) as auth_client:
                        started_auth = await auth_client.post(
                            "/api/v1/auth/native/start",
                            json={"code_challenge": challenge},
                        )
                        assert started_auth.status_code == 200
                        state = parse_qs(
                            urlsplit(
                                started_auth.json()["authorization_url"]
                            ).query
                        )["state"][0]
                        callback = await auth_client.get(
                            "/api/v1/auth/callback",
                            params={"code": "provider-code", "state": state},
                            follow_redirects=False,
                        )
                        assert callback.status_code == 303
                        exchange_code = parse_qs(
                            urlsplit(callback.headers["location"]).query
                        )["code"][0]
                        exchanged = await auth_client.post(
                            "/api/v1/auth/native/exchange",
                            json={
                                "code": exchange_code,
                                "code_verifier": verifier,
                            },
                        )
                        assert exchanged.status_code == 200
                        native_headers = {
                            "Authorization": (
                                f"Bearer {exchanged.json()['access_token']}"
                            )
                        }
                        authenticated = await auth_client.get(
                            "/api/v1/auth/native/session",
                            headers=native_headers,
                        )
                        assert authenticated.status_code == 200
                        assert authenticated.json()["github_login"] == "fgomensoro"

                    with sync_engine.begin() as connection:
                        owner_id = connection.execute(
                            text(
                                "SELECT id FROM owners WHERE github_user_id = :github_id"
                            ),
                            {"github_id": APPROVED_GITHUB_USER_ID},
                        ).scalar_one()
                        connection.execute(
                            text(
                                "INSERT INTO learner_settings "
                                "(owner_id, timezone, study_start_date) "
                                "VALUES (:owner, 'America/Los_Angeles', :start_date)"
                            ),
                            {"owner": owner_id, "start_date": date(2026, 8, 24)},
                        )

                    async with AsyncClient(
                        transport=transport,
                        base_url="https://app.example.test",
                    ) as first_native_client:
                        staged = await first_native_client.post(
                            "/api/v1/roadmap-imports",
                            data={"package_kind": "zip"},
                            files={
                                "package": (
                                    "month-v1.zip",
                                    package_bytes,
                                    "application/zip",
                                )
                            },
                            headers={
                                **native_headers,
                                "Idempotency-Key": "foundation-roadmap",
                            },
                        )
                        assert staged.status_code == 201, staged.text
                        staged_payload = staged.json()
                        assert isinstance(staged_payload["id"], int)
                        assert staged_payload["id"] > 0
                        assert {
                            key: value
                            for key, value in staged_payload.items()
                            if key != "id"
                        } == expected_import_response
                        assert {
                            **staged_payload,
                            "id": parity["responses"]["roadmap_import"]["id"],
                        } == parity["responses"]["roadmap_import"]

                        replay = await first_native_client.post(
                            "/api/v1/roadmap-imports",
                            data={"package_kind": "zip"},
                            files={
                                "package": (
                                    "month-v1.zip",
                                    package_bytes,
                                    "application/zip",
                                )
                            },
                            headers={
                                **native_headers,
                                "Idempotency-Key": "foundation-roadmap",
                            },
                        )
                        assert replay.status_code == 201
                        assert replay.json() == staged_payload

                        approved = await first_native_client.post(
                            f"/api/v1/roadmap-imports/{staged_payload['id']}/approve",
                            headers=native_headers,
                        )
                        assert approved.status_code == 200, approved.text
                        approved_payload = approved.json()
                        expected_approved_payload = {
                            **parity["responses"]["roadmap_version"],
                            "id": approved_payload["id"],
                            "state": "approved",
                        }
                        assert approved_payload == expected_approved_payload
                        activated = await first_native_client.post(
                            f"/api/v1/roadmap-versions/{approved_payload['id']}/activate",
                            headers=native_headers,
                        )
                        assert activated.status_code == 200, activated.text
                        activated_payload = activated.json()
                        assert activated_payload == {
                            **parity["responses"]["roadmap_version"],
                            "id": approved_payload["id"],
                        }

                        today = await first_native_client.get(
                            "/api/v1/today?date=2026-08-24", headers=native_headers
                        )
                        assert today.status_code == 200, today.text
                        today_payload = today.json()
                        expected_today = parity["responses"]["today"]
                        expected_day_tasks = tuple(
                            task
                            for task in expected_roadmap.tasks
                            if task.week == 1 and task.day == 1
                        )
                        assert len(today_payload["tasks"]) == len(expected_day_tasks) == 7
                        activity_ids_by_stable_id = {
                            item["stable_id"]: item["activity_id"]
                            for item in today_payload["tasks"]
                        }
                        assert set(activity_ids_by_stable_id) == {
                            task.stable_id for task in expected_day_tasks
                        }
                        expected_tasks = [
                            {
                                "activity_id": activity_ids_by_stable_id[
                                    expected_task.stable_id
                                ],
                                "roadmap_order": expected_task.order,
                                "stable_id": expected_task.stable_id,
                                "block": expected_task.block,
                                "state": "ready",
                                "objective": expected_task.objective,
                                "timebox_minutes": expected_task.timebox_minutes,
                                "source_references": [
                                    {
                                        "path": expected_task.source_path,
                                        "anchor": expected_task.source_heading,
                                    }
                                ],
                                "required_output": list(expected_task.required_output),
                                "pass_criteria": list(expected_task.pass_criteria),
                                "allowed_ai_role": expected_task.allowed_ai_role,
                                "evidence_requirements": list(
                                    expected_task.evidence_requirements
                                ),
                                "required": expected_task.required,
                                "optimistic_version": 1,
                            }
                            for expected_task in expected_day_tasks
                        ]
                        required_blocks = [
                            {
                                "name": task.block,
                                "planned_minutes": task.timebox_minutes,
                                "activity_ids": [
                                    activity_ids_by_stable_id[task.stable_id]
                                ],
                            }
                            for task in expected_day_tasks
                            if task.required
                        ]
                        day_id = today_payload["day_id"]
                        assert isinstance(day_id, int) and day_id > 0
                        expected_today_payload = {
                            "local_date": expected_today["local_date"],
                            "timezone": expected_today["timezone"],
                            "day_id": day_id,
                            "day_type": expected_today["day_type"],
                            "day_status": expected_today["day_status"],
                            "roadmap": {
                                "version_id": activated_payload["id"],
                                "version_key": expected_roadmap.roadmap_version,
                                "version_number": 1,
                                "month": 1,
                                "week": 1,
                                "day": 1,
                            },
                            "total_planned_minutes": expected_today[
                                "total_planned_minutes"
                            ],
                            "time_policy": expected_today["time_policy"],
                            "required_blocks": required_blocks,
                            "tasks": expected_tasks,
                            "corrections": [],
                            "interviews": [],
                            "awaiting_self_reviews": [],
                            "analyses": [],
                            "primary_continue": {
                                "kind": "start_activity",
                                "target_id": expected_tasks[0]["activity_id"],
                                "label": "Start next required activity",
                                "allowed_ai_role": expected_tasks[0]["allowed_ai_role"],
                            },
                        }
                        assert (
                            _without_fields(today_payload, TODAY_VOLATILE_FIELDS)
                            == expected_today_payload
                        )
                        datetime.fromisoformat(today_payload["source_updated_at"])
                        assert len(today_payload["read_model_version"]) == 64
                        int(today_payload["read_model_version"], 16)
                        assert today_payload["etag"] == (
                            f'"{today_payload["read_model_version"]}"'
                        )
                        assert today.headers["ETag"] == today_payload["etag"]
                        reading = next(
                            item
                            for item in today_payload["tasks"]
                            if item["block"] == "technical_learning"
                        )
                        assert {
                            **reading,
                            "activity_id": expected_today["tasks"][0]["activity_id"],
                        } == expected_today["tasks"][0]
                        activity_id = int(reading["activity_id"])
                        path = f"/api/v1/activities/{activity_id}"
                        detail = await first_native_client.get(path, headers=native_headers)
                        assert detail.status_code == 200
                        detail_payload = detail.json()
                        expected_reading = next(
                            task
                            for task in expected_day_tasks
                            if task.block == "technical_learning"
                        )
                        assert detail_payload == {
                            "id": activity_id,
                            "study_day_id": today_payload["day_id"],
                            "state": "ready",
                            "optimistic_version": 1,
                            "classification": "required",
                            "stronger_evidence_id": None,
                            "activity_focused_seconds": 0,
                            "day_focused_minutes": 0,
                            "hard_stop_recommended": False,
                            "open_timer": None,
                            "source_hidden": False,
                            "task_contract": {
                                "stable_id": expected_reading.stable_id,
                                "block": expected_reading.block,
                                "objective": expected_reading.objective,
                                "timebox_minutes": expected_reading.timebox_minutes,
                                "required": expected_reading.required,
                                "source_references": [
                                    {
                                        "path": expected_reading.source_path,
                                        "anchor": expected_reading.source_heading,
                                    }
                                ],
                                "required_output": list(
                                    expected_reading.required_output
                                ),
                                "pass_criteria": list(expected_reading.pass_criteria),
                                "evidence_requirements": list(
                                    expected_reading.evidence_requirements
                                ),
                                "allowed_ai_role": expected_reading.allowed_ai_role,
                                "procedure": [
                                    item.to_dict() for item in expected_reading.procedure
                                ],
                                "constraints": list(expected_reading.constraints),
                                "exercise_type": expected_reading.exercise_type,
                                "mapping_version": expected_reading.mapping_version,
                            },
                            "committed_output": None,
                            "self_review": None,
                        }
                        assert {
                            **detail_payload,
                            "id": parity["responses"]["activity"]["id"],
                            "study_day_id": parity["responses"]["activity"][
                                "study_day_id"
                            ],
                        } == parity["responses"]["activity"]
                        activity_states = [detail_payload["state"]]
                        started = await mutate(
                            first_native_client,
                            path + "/start",
                            {"expected_version": 1},
                            "foundation-start",
                        )
                        started_payload = await assert_activity_response(
                            first_native_client,
                            started,
                            activity_path=path,
                            expected_state="active",
                            expected_version=2,
                            expected_source_hidden=False,
                            timer_open=True,
                        )
                        activity_states.append(started_payload["state"])
                        paused = await mutate(
                            first_native_client,
                            path + "/pause",
                            {"expected_version": 2, "client_sequence": 1},
                            "foundation-pause",
                        )
                        paused_payload = await assert_activity_response(
                            first_native_client,
                            paused,
                            activity_path=path,
                            expected_state="paused",
                            expected_version=3,
                            expected_source_hidden=False,
                            timer_open=False,
                        )
                        activity_states.append(paused_payload["state"])

                    async with AsyncClient(
                        transport=transport,
                        base_url="https://app.example.test",
                    ) as resumed_native_client:
                        resumed = await mutate(
                            resumed_native_client,
                            path + "/resume",
                            {"expected_version": 3},
                            "foundation-resume",
                        )
                        resumed_payload = await assert_activity_response(
                            resumed_native_client,
                            resumed,
                            activity_path=path,
                            expected_state="active",
                            expected_version=4,
                            expected_source_hidden=False,
                            timer_open=True,
                        )
                        activity_states.append(resumed_payload["state"])
                        hidden = await mutate(
                            resumed_native_client,
                            path + "/source-visibility",
                            {"expected_version": 4, "hidden": True},
                            "foundation-hide",
                        )
                        await assert_activity_response(
                            resumed_native_client,
                            hidden,
                            activity_path=path,
                            expected_state="active",
                            expected_version=5,
                            expected_source_hidden=True,
                            timer_open=True,
                        )
                        output = parity["journey"]["output"]
                        commit_body = {
                            "expected_version": 5,
                            "client_sequence": 1,
                            "output": output,
                            "artifact_refs": [],
                        }
                        committed = await mutate(
                            resumed_native_client,
                            path + "/commit-output",
                            commit_body,
                            "foundation-commit",
                        )
                        assert committed.status_code == 200, committed.text
                        committed_payload = committed.json()
                        assert isinstance(committed_payload["attempt_id"], int)
                        assert committed_payload["attempt_id"] > 0
                        assert len(committed_payload["commitment_sha256"]) == 64
                        int(committed_payload["commitment_sha256"], 16)
                        assert committed_payload == {
                            "activity_id": activity_id,
                            "state": "output_committed",
                            "optimistic_version": 6,
                            "attempt_id": committed_payload["attempt_id"],
                            "commitment_sha256": committed_payload[
                                "commitment_sha256"
                            ],
                            "artifact_ids": [],
                        }
                        activity_states.append(committed_payload["state"])
                        replayed_commit = await mutate(
                            resumed_native_client,
                            path + "/commit-output",
                            commit_body,
                            "foundation-commit",
                        )
                        assert replayed_commit.json() == committed_payload
                        review_body = {
                            "expected_version": 6,
                            **parity["journey"]["self_review"],
                        }
                        reviewed = await mutate(
                            resumed_native_client,
                            path + "/self-review",
                            review_body,
                            "foundation-review",
                        )
                        assert reviewed.status_code == 200, reviewed.text
                        reviewed_payload = reviewed.json()
                        assert isinstance(reviewed_payload["self_review_id"], int)
                        assert reviewed_payload["self_review_id"] > 0
                        assert reviewed_payload == {
                            "activity_id": activity_id,
                            "state": "self_review_complete",
                            "optimistic_version": 7,
                            "self_review_id": reviewed_payload["self_review_id"],
                            "attempt_id": committed_payload["attempt_id"],
                            "self_score": review_body["self_score"],
                        }
                        activity_states.append(reviewed_payload["state"])
                        assert activity_states == parity["journey"]["activity_states"]
                        final_detail = await resumed_native_client.get(
                            path,
                            headers=native_headers,
                        )
                        assert final_detail.status_code == 200, final_detail.text
                        final_detail_payload = final_detail.json()
                        assert final_detail_payload["state"] == "self_review_complete"
                        assert final_detail_payload["optimistic_version"] == 7
                        assert final_detail_payload["source_hidden"] is True
                        assert final_detail_payload["open_timer"] is None
                        committed_summary = final_detail_payload["committed_output"]
                        assert committed_summary["attempt_id"] == committed_payload[
                            "attempt_id"
                        ]
                        assert committed_summary["attempt_kind"] == "attempt_a"
                        assert committed_summary["commitment_sha256"] == (
                            committed_payload["commitment_sha256"]
                        )
                        assert committed_summary["artifact_ids"] == []
                        datetime.fromisoformat(committed_summary["committed_at"])
                        task_context = committed_summary["contract_payload"][
                            "task_context"
                        ]
                        assert isinstance(task_context["task_definition_id"], int)
                        assert task_context["task_definition_id"] > 0
                        assert committed_summary["contract_payload"] == {
                            "contract_version": output["contract_version"],
                            "task_context": {
                                "task_definition_id": task_context[
                                    "task_definition_id"
                                ],
                                "task_stable_id": expected_reading.stable_id,
                                "exercise_type": expected_reading.exercise_type,
                                "mapping_version": expected_reading.mapping_version,
                                "roadmap_version_key": expected_roadmap.roadmap_version,
                                "time_limit_minutes": expected_reading.timebox_minutes,
                            },
                            "output": {
                                key: value
                                for key, value in output.items()
                                if key != "contract_version"
                            },
                        }
                        review_summary = final_detail_payload["self_review"]
                        datetime.fromisoformat(review_summary["submitted_at"])
                        assert {
                            key: value
                            for key, value in review_summary.items()
                            if key != "submitted_at"
                        } == {
                            "id": reviewed_payload["self_review_id"],
                            "attempt_id": committed_payload["attempt_id"],
                            **parity["journey"]["self_review"],
                        }

                    async with factory() as session:
                        async with transaction_scope(session):
                            await seed_config(
                                bundle,
                                owner_id=owner_id,
                                session=session,
                                apply=True,
                            )
                    exercise_config = bundle.exercise(
                        "integration_diagram_and_explanation"
                    )
                    rubric = bundle.portfolio
                    applicable = tuple(
                        impact
                        for impact in exercise_config.impacts
                        if impact.condition == "always"
                    )
                    evidence_command = EvidenceEvaluationCommand(
                        activity_id=activity_id,
                        attempt_id=int(committed_payload["attempt_id"]),
                        config_version_key=bundle.version_key,
                        exercise_type=exercise_config.slug,
                        mapping_version=exercise_config.mapping_version,
                        formula_version=bundle.formula.version,
                        rubric_slug=rubric.slug,
                        rubric_version=rubric.version,
                        practice_mode=exercise_config.evidence_mode,
                        assistance="ai_after_committed_attempt",
                        evaluator="ai_rubric_reviewer",
                        difficulty="standard",
                        ai_role="reviewer",
                        evaluated_at=datetime.now(UTC),
                        artifact_ids=(),
                        observation_ids=(),
                        transcript_available=False,
                        audio_available=False,
                        written_english_available=False,
                        scored_recording=False,
                        dimensions=tuple(
                            DimensionEvaluationInput(
                                dimension_slug=dimension.slug,
                                availability="scored",
                                score=min(dimension.maximum, Decimal("3")),
                            )
                            for dimension in rubric.dimensions
                        ),
                        skill_dimension_subsets=tuple(
                            SkillDimensionSubsetInput(
                                skill_slug=impact.skill_slug,
                                dimension_slugs=(rubric.dimensions[index].slug,),
                            )
                            for index, impact in enumerate(applicable)
                        ),
                    )
                    async with factory() as session:
                        evidence = await EvidenceService(
                            SqlAlchemyEvidenceRepository(session)
                        ).record(
                            owner_id=owner_id,
                            command=evidence_command,
                            idempotency_key="foundation-evidence",
                        )
                    async with factory() as session:
                        replayed_evidence = await EvidenceService(
                            SqlAlchemyEvidenceRepository(session)
                        ).record(
                            owner_id=owner_id,
                            command=evidence_command,
                            idempotency_key="foundation-evidence",
                        )
                        assert replayed_evidence == evidence
                        reader = SqlAlchemyEvidenceRepository(session)
                        first_projection = await reader.list_skills(owner_id=owner_id)
                    async with factory() as session:
                        second_projection = await SqlAlchemyEvidenceRepository(
                            session
                        ).list_skills(owner_id=owner_id)
                    assert first_projection == second_projection
                    measured = tuple(
                        item
                        for item in first_projection.items
                        if item.latest_snapshot is not None
                    )
                    assert len(measured) == len(applicable)
                    assert all(
                        {
                            item.event_id
                            for item in skill.latest_snapshot.manifest
                        }.issubset(set(evidence.evidence_event_ids))
                        for skill in measured
                    )

                    expected_notification = parity["responses"]["notifications"][
                        "items"
                    ][0]
                    now = datetime.fromisoformat(expected_notification["created_at"])
                    async with factory() as session:
                        async with transaction_scope(session):
                            session.add(
                                OutboxEvent(
                                    owner_id=owner_id,
                                    aggregate_type="activity",
                                    aggregate_id=activity_id,
                                    event_type="activity.feedback_ready",
                                    payload_schema_version=1,
                                    payload={
                                        "schema_version": 1,
                                        "subject_id": activity_id,
                                    },
                                    occurred_at=now,
                                    published_at=None,
                                    attempts=0,
                                    idempotency_key="foundation-feedback",
                                )
                            )
                    async with factory() as session:
                        delivery = SqlAlchemyNotificationRepository(
                            session,
                            clock=lambda: now,
                        )
                        first_delivery = await delivery.deliver_outbox(limit=100)
                        second_delivery = await delivery.deliver_outbox(limit=100)
                        assert len(first_delivery.notification_ids) == 1
                        assert second_delivery.notification_ids == ()

                    async with AsyncClient(
                        transport=transport,
                        base_url="https://app.example.test",
                    ) as final_native_client:
                        skills = await final_native_client.get(
                            "/api/v1/skills", headers=native_headers
                        )
                        assert skills.status_code == 200
                        assert skills.json() == first_projection.model_dump(mode="json")
                        expected_unassessed = next(
                            item
                            for item in parity["responses"]["skills"]["items"]
                            if item["latest_snapshot"] is None
                        )
                        actual_unassessed = next(
                            item
                            for item in skills.json()["items"]
                            if item["slug"] == expected_unassessed["slug"]
                        )
                        assert actual_unassessed == expected_unassessed
                        portfolio = await final_native_client.get(
                            "/api/v1/portfolio-judgment", headers=native_headers
                        )
                        assert portfolio.status_code == 200
                        assert portfolio.json() == parity["responses"]["portfolio"]

                        notifications = await final_native_client.get(
                            "/api/v1/notifications", headers=native_headers
                        )
                        assert notifications.status_code == 200
                        notifications_payload = notifications.json()
                        assert len(notifications_payload["items"]) == 1
                        notification = notifications_payload["items"][0]
                        assert datetime.fromisoformat(notification["created_at"]) == now
                        assert {
                            "items": [
                                {
                                    **notification,
                                    "id": expected_notification["id"],
                                    "subject_id": expected_notification["subject_id"],
                                    "created_at": expected_notification["created_at"],
                                }
                            ],
                            "next_cursor": notifications_payload["next_cursor"],
                        } == parity["responses"]["notifications"]
                        assert notification["subject_id"] == activity_id
                        assert notification["id"] == first_delivery.notification_ids[0]
                        notification_id = notification["id"]
                        first_read = await final_native_client.post(
                            f"/api/v1/notifications/{notification_id}/read",
                            headers=native_headers,
                        )
                        second_read = await final_native_client.post(
                            f"/api/v1/notifications/{notification_id}/read",
                            headers=native_headers,
                        )
                        assert first_read.status_code == second_read.status_code == 200
                        first_read_payload = first_read.json()
                        assert second_read.json() == first_read_payload
                        datetime.fromisoformat(first_read_payload["read_at"])
                        assert {
                            key: value
                            for key, value in first_read_payload.items()
                            if key != "read_at"
                        } == {
                            key: value
                            for key, value in notification.items()
                            if key != "read_at"
                        }
                        refreshed_today = await final_native_client.get(
                            "/api/v1/today?date=2026-08-24", headers=native_headers
                        )
                        updated = next(
                            item
                            for item in refreshed_today.json()["tasks"]
                            if item["activity_id"] == activity_id
                        )
                        assert updated["state"] == "self_review_complete"
                        async with factory() as session:
                            expected_refreshed_today = await TodayService(
                                SqlAlchemyTodayRepository(session)
                            ).get_today(
                                owner_id=owner_id,
                                local_date=date(2026, 8, 24),
                            )
                        assert refreshed_today.json() == (
                            expected_refreshed_today.model_dump(mode="json")
                        )

                async with factory() as session:
                    assert await session.scalar(
                        select(func.count()).select_from(RoadmapImport)
                    ) == 1
                    assert await session.scalar(
                        select(func.count()).select_from(Attempt)
                    ) == 1
                    assert await session.scalar(
                        select(func.count()).select_from(SelfReview)
                    ) == 1
                    assert await session.scalar(
                        select(func.count()).select_from(RubricEvaluation)
                    ) == 1
                    assert await session.scalar(
                        select(func.count()).select_from(SkillEvidenceEvent)
                    ) == len(applicable)
                    assert await session.scalar(
                        select(func.count()).select_from(Notification)
                    ) == 1
                    assert await session.scalar(
                        select(func.count())
                        .select_from(CommandReceipt)
                        .where(CommandReceipt.command_scope == "activity.commit-output")
                    ) == 1
                    activity = await session.get(ActivityInstance, activity_id)
                    assert activity is not None
                    assert activity.state == "self_review_complete"
                    persisted_import = (
                        await session.scalars(select(RoadmapImport))
                    ).one()
                    object_key = persisted_import.object_key
                    assert persisted_import.package_hash.hex() == parity[
                        "source_package"
                    ]["sha256"]

                fresh_store = S3ObjectStore(
                    endpoint_url=object_store["TAMFORGE_OBJECT_STORE_ENDPOINT"],
                    region="us-east-1",
                    bucket=object_store["TAMFORGE_OBJECT_STORE_BUCKET"],
                    access_key=object_store["TAMFORGE_OBJECT_STORE_ACCESS_KEY"],
                    secret_key=object_store["TAMFORGE_OBJECT_STORE_SECRET_KEY"],
                )
                stored = await fresh_store.stat(object_key)
                assert stored is not None
                assert stored.sha256 == parity["source_package"]["sha256"]
                assert stored.byte_length == parity["source_package"]["byte_length"]
                async with fresh_store.open(object_key) as chunks:
                    persisted_package = b"".join([chunk async for chunk in chunks])
                assert persisted_package == package_bytes
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()
