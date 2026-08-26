import assert from "node:assert/strict";
import test from "node:test";

import { verifyComposeText } from "./verify_compose.mjs";

const APPROVED_COMPOSE = `services:
  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "127.0.0.1:5432:5432"
  minio:
    image: minio/minio:RELEASE.2024-06-13T22-53-53Z
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9001:9001"
`;

test("accepts the exact approved local Compose shape", () => {
  assert.doesNotThrow(() => verifyComposeText(APPROVED_COMPOSE));
});

const unsafePortCases = {
  "protocol suffix": `      - "127.0.0.1:5432:5432/tcp"`,
  hostname: `      - "localhost:5432:5432"`,
  IPv6: `      - "[::1]:5432:5432"`,
  "single-port publishing": `      - "5432"`,
  "long syntax": "      - target: 5432\n        published: 5432",
  "mixed recognized and unsafe entries": `      - "5432:5432/tcp"`,
};

for (const [name, replacement] of Object.entries(unsafePortCases)) {
  test(`rejects ${name}`, () => {
    const compose = APPROVED_COMPOSE.replace(`      - "127.0.0.1:5432:5432"`, replacement);
    assert.throws(() => verifyComposeText(compose));
  });
}

const unsafeMinioImages = {
  latest: "minio/minio:latest",
  edge: "minio/minio:edge",
  interpolated: "minio/minio:${MINIO_TAG}",
  digestless: "minio/minio",
  digest: "minio/minio@sha256:0123456789abcdef",
};

for (const [name, image] of Object.entries(unsafeMinioImages)) {
  test(`rejects ${name} MinIO image references`, () => {
    const compose = APPROVED_COMPOSE.replace(
      "minio/minio:RELEASE.2024-06-13T22-53-53Z",
      image,
    );
    assert.throws(() => verifyComposeText(compose));
  });
}
