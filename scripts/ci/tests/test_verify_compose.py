from __future__ import annotations

import pytest

from scripts.ci.verify_bootstrap import verify_bootstrap
from scripts.ci.verify_compose import APPROVED_MINIO_IMAGE, verify_compose_text

APPROVED_COMPOSE = f"""services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: tamforge
      POSTGRES_USER: tamforge
      POSTGRES_PASSWORD: tamforge
    ports:
      - \"127.0.0.1:54329:5432\"
    volumes:
      - tamforge-postgres:/var/lib/postgresql/data
  minio:
    image: {APPROVED_MINIO_IMAGE}
    command: server /data --console-address \":9001\"
    environment:
      MINIO_ROOT_USER: tamforge
      MINIO_ROOT_PASSWORD: tamforge-local
    ports:
      - \"127.0.0.1:9000:9000\"
      - \"127.0.0.1:9001:9001\"
    volumes:
      - tamforge-minio:/data
volumes:
  tamforge-postgres:
  tamforge-minio:
"""


def test_accepts_exact_approved_local_compose_shape() -> None:
    assert verify_compose_text(APPROVED_COMPOSE).published_ports == (
        "127.0.0.1:54329:5432",
        "127.0.0.1:9000:9000",
        "127.0.0.1:9001:9001",
    )


def test_accepts_safe_quoting_comments_and_inline_arrays() -> None:
    compose = (
        APPROVED_COMPOSE.replace(
            f"image: {APPROVED_MINIO_IMAGE}",
            f'image: "{APPROVED_MINIO_IMAGE}" # pinned local image',
        )
        .replace(
            '    ports:\n      - "127.0.0.1:9000:9000"\n      - "127.0.0.1:9001:9001"',
            '    ports: ["127.0.0.1:9000:9000", "127.0.0.1:9001:9001"] # loopback only',
        )
    )
    assert verify_compose_text(compose).minio_image == APPROVED_MINIO_IMAGE


def test_rejects_explicit_standard_yaml_tags() -> None:
    compose = APPROVED_COMPOSE.replace(
        "image: pgvector/pgvector:pg16",
        "image: !!str pgvector/pgvector:pg16",
    )
    with pytest.raises(ValueError, match="tags"):
        verify_compose_text(compose)


@pytest.mark.parametrize(
    "replacement",
    (
        '      - "127.0.0.1:54329:5432/tcp"',
        '      - "localhost:54329:5432"',
        '      - "[::1]:54329:5432"',
        '      - "54329"',
        "      - target: 5432\n        published: 54329",
        '      - "54329:5432/tcp"',
    ),
)
def test_rejects_unsafe_port_forms(replacement: str) -> None:
    compose = APPROVED_COMPOSE.replace('      - "127.0.0.1:54329:5432"', replacement)
    with pytest.raises(ValueError):
        verify_compose_text(compose)


@pytest.mark.parametrize(
    "image",
    (
        "minio/minio:latest",
        "minio/minio:edge",
        "minio/minio:${MINIO_TAG}",
        "minio/minio",
        "minio/minio@sha256:0123456789abcdef",
    ),
)
def test_rejects_unpinned_or_interpolated_minio_images(image: str) -> None:
    with pytest.raises(ValueError):
        verify_compose_text(APPROVED_COMPOSE.replace(APPROVED_MINIO_IMAGE, image))


@pytest.mark.parametrize(
    "replacement",
    (
        '  rogue:\n    image: pgvector/pgvector:pg16\n    ports: ["0.0.0.0:4321:4321"]\n  minio:',
        "  rogue:\n    image: pgvector/pgvector:pg16\n    ports: # review this mapping\n"
        '      - "0.0.0.0:4321:4321"\n  minio:',
        '  rogue-minio:\n    image: "minio/minio:edge"\n  minio:',
        '  rogue-minio:\n    image: "minio/minio:edge" # review this image\n  minio:',
    ),
)
def test_rejects_unsafe_fields_on_unexpected_services(replacement: str) -> None:
    with pytest.raises(ValueError):
        verify_compose_text(APPROVED_COMPOSE.replace("  minio:", replacement))


@pytest.mark.parametrize(
    "compose",
    (
        """defaults: &defaults
  image: pgvector/pgvector:pg16
services:
  postgres:
    <<: *defaults
    ports:
      - \"127.0.0.1:54329:5432\"
  minio:
    image: minio/minio:RELEASE.2024-06-13T22-53-53Z
    ports:
      - \"127.0.0.1:9000:9000\"
      - \"127.0.0.1:9001:9001\"
volumes:
  tamforge-postgres:
  tamforge-minio:
""",
        APPROVED_COMPOSE.replace(
            '    ports:\n      - "127.0.0.1:54329:5432"\n',
            '    ports:\n      - "127.0.0.1:54329:5432"\n'
            '    ports:\n      - "127.0.0.1:54329:5432"\n',
        ),
        f"{APPROVED_COMPOSE}\n---\nservices: {{}}",
        "services: [",
        APPROVED_COMPOSE.replace("services:", "service:"),
        "services: {}\nvolumes: {}\n",
        APPROVED_COMPOSE.replace(
            "  minio:",
            "  rogue:\n    image: pgvector/pgvector:pg16\n  minio:",
        ),
    ),
)
def test_rejects_unsafe_or_unexpected_compose_documents(compose: str) -> None:
    with pytest.raises(ValueError):
        verify_compose_text(compose)


def test_bootstrap_verifies_compose_without_node_runtime(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "compose.dev.yml").write_text(APPROVED_COMPOSE, encoding="utf-8")
    result = verify_bootstrap(tmp_path)
    assert result.published_ports[-1] == "127.0.0.1:9001:9001"
