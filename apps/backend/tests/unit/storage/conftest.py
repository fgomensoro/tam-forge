from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.client import Config
from botocore.exceptions import ClientError
from moto import mock_aws


class ChecksumAwareMotoClient:
    """Fill Moto's current S3 checksum-validation and HEAD response gap."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.checksums: dict[tuple[str, str], str] = {}
        self.last_put_kwargs: dict[str, Any] | None = None
        self.last_head_kwargs: dict[str, Any] | None = None
        self.head_calls = 0

    def put_object(self, **kwargs: Any) -> Any:
        self.last_put_kwargs = dict(kwargs)
        checksum = kwargs.get("ChecksumSHA256")
        if checksum is not None:
            body = kwargs["Body"]
            if isinstance(body, bytes):
                payload = body
            else:
                position = body.tell()
                payload = body.read()
                body.seek(position)
            actual = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
            if checksum != actual:
                raise ClientError(
                    {"Error": {"Code": "BadDigest", "Message": "checksum mismatch"}},
                    "PutObject",
                )
        response = self._client.put_object(**kwargs)
        if checksum is not None:
            self.checksums[(kwargs["Bucket"], kwargs["Key"])] = checksum
        return response

    def head_object(self, **kwargs: Any) -> Any:
        self.head_calls += 1
        self.last_head_kwargs = dict(kwargs)
        response = self._client.head_object(**kwargs)
        if kwargs.get("ChecksumMode") == "ENABLED":
            checksum = self.checksums.get((kwargs["Bucket"], kwargs["Key"]))
            if checksum is not None:
                response["ChecksumSHA256"] = checksum
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


@pytest.fixture
def moto_s3_client() -> Iterator[ChecksumAwareMotoClient]:
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test-access",
            aws_secret_access_key="test-secret",
            config=Config(signature_version="s3v4"),
        )
        client.create_bucket(Bucket="tam-forge-test")
        yield ChecksumAwareMotoClient(client)
