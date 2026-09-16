"""Two submitted transcripts become stored turns through the real queue and worker."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tamforge_backend.database import database_url_to_sync
from tamforge_backend.main import create_app
from tamforge_backend.storage.fake import InMemoryObjectStore
from tamforge_backend.workers.speech import analysis_step

pytestmark = pytest.mark.integration

# The submission test owns the seeding helpers; this file shares them by path because the
# integration directories are not packages.
_SUBMISSION = importlib.util.spec_from_file_location(
    "test_transcript_submission", Path(__file__).with_name("test_transcript_submission.py")
)
assert _SUBMISSION is not None and _SUBMISSION.loader is not None
_submission = importlib.util.module_from_spec(_SUBMISSION)
sys.modules[_SUBMISSION.name] = _submission  # dataclasses resolve the module by name
_SUBMISSION.loader.exec_module(_submission)
Seeded = _submission.Seeded
_settings = _submission._settings
_transcript_body = _submission._transcript_body


@pytest.fixture(scope="module")
def engine(test_database_url: str) -> Iterator[Engine]:
    _submission._reset(test_database_url)
    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        yield engine
    finally:
        engine.dispose()
        _submission._reset(test_database_url)


@pytest.fixture
def seeded(engine: Engine) -> Seeded:  # type: ignore[valid-type]
    token = (uuid4().hex + uuid4().hex)[:43]
    with engine.begin() as connection:
        owner_id = _submission._insert_owner_with_native_session(connection, token=token)
        recording_id = _submission._insert_stored_recording(connection, owner_id=owner_id)
    return Seeded(owner_id=owner_id, token=token, recording_id=recording_id)


def _system_body() -> dict[str, object]:
    return _transcript_body(
        track="system_audio",
        segments=[
            {
                "text": "tell me about retries",
                "start_ms": 0,
                "end_ms": 700,
                "words": [
                    {"text": "tell", "start_ms": 0, "end_ms": 200, "probability": 0.9},
                    {"text": " me", "start_ms": 200, "end_ms": 300, "probability": 0.9},
                    {"text": " about", "start_ms": 300, "end_ms": 500, "probability": 0.9},
                    {"text": " retries", "start_ms": 500, "end_ms": 700, "probability": 0.9},
                ],
            }
        ],
    )


def _microphone_body() -> dict[str, object]:
    return _transcript_body(
        segments=[
            {
                "text": "hello there",
                "start_ms": 1_200,
                "end_ms": 2_100,
                "words": [
                    {"text": "hello", "start_ms": 1_200, "end_ms": 1_600, "probability": 0.98},
                    {"text": " there", "start_ms": 1_600, "end_ms": 2_100, "probability": 0.3},
                ],
            }
        ]
    )


def test_transcripts_are_analysed_by_the_worker_and_read_back_as_turns(
    seeded: Seeded, test_database_url: str
) -> None:
    app = create_app(_settings(test_database_url))
    app.state.object_store = InMemoryObjectStore()
    headers = {"Authorization": f"Bearer {seeded.token}"}
    base = f"/api/v1/recordings/{seeded.recording_id}"

    with TestClient(app) as client:
        before = client.get(f"{base}/analysis", headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()["status"] == "not_requested"

        for body, key in ((_system_body(), "system"), (_microphone_body(), "mic")):
            submitted = client.post(
                f"{base}/transcripts",
                json=body,
                headers={**headers, "Idempotency-Key": f"transcript-{key}"},
            )
            assert submitted.status_code == 201, submitted.text

        queued = client.get(f"{base}/analysis", headers=headers)
        assert queued.json()["status"] == "queued"
        assert queued.json()["turns"] == []

        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
        engine_async = create_async_engine(async_url)
        try:
            factory = async_sessionmaker(engine_async, expire_on_commit=False)
            assert asyncio.run(analysis_step(factory)) is None
        finally:
            asyncio.run(engine_async.dispose())

        published = client.get(f"{base}/analysis", headers=headers)
        assert published.status_code == 200, published.text
        payload = published.json()
        assert payload["status"] == "published"
        assert payload["analysis_version"] == "speech-analysis-v1"
        assert [(t["speaker"], t["text"]) for t in payload["turns"]] == [
            ("other", "tell me about retries"),
            ("learner", "hello there"),
        ]
        assert payload["turns"][1]["start_ms"] == 1_200
        assert payload["metrics"]["response_latency_ms"] == 500
        assert payload["metrics"]["filler_count"] == 0
        assert payload["failure_category"] is None

        unknown = client.get(f"/api/v1/recordings/{uuid4()}/analysis", headers=headers)
        assert unknown.status_code == 404
