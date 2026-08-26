import assert from "node:assert/strict";
import test from "node:test";

import { verifyComposeText } from "./verify_compose.mjs";

const APPROVED_COMPOSE = `services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: tamforge
      POSTGRES_USER: tamforge
      POSTGRES_PASSWORD: tamforge
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - tamforge-postgres:/var/lib/postgresql/data
  minio:
    image: minio/minio:RELEASE.2024-06-13T22-53-53Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: tamforge
      MINIO_ROOT_PASSWORD: tamforge-local
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9001:9001"
    volumes:
      - tamforge-minio:/data
volumes:
  tamforge-postgres:
  tamforge-minio:
`;

test("accepts the exact approved local Compose shape", () => {
  assert.doesNotThrow(() => verifyComposeText(APPROVED_COMPOSE));
});

test("accepts semantically equivalent safe quoting, comments, and inline arrays", () => {
  const compose = APPROVED_COMPOSE
    .replace(
      "image: minio/minio:RELEASE.2024-06-13T22-53-53Z",
      'image: "minio/minio:RELEASE.2024-06-13T22-53-53Z" # pinned local image',
    )
    .replace(
      '    ports:\n      - "127.0.0.1:9000:9000"\n      - "127.0.0.1:9001:9001"',
      '    ports: ["127.0.0.1:9000:9000", "127.0.0.1:9001:9001"] # loopback only',
    );
  assert.doesNotThrow(() => verifyComposeText(compose));
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

const EXTRA_SERVICE_HEADER = `  rogue:
    image: pgvector/pgvector:pg16
`;

test("rejects unsafe inline ports added to an unexpected service", () => {
  const compose = APPROVED_COMPOSE.replace(
    "  minio:",
    `${EXTRA_SERVICE_HEADER}    ports: ["0.0.0.0:4321:4321"]\n  minio:`,
  );
  assert.throws(() => verifyComposeText(compose));
});

test("rejects a commented ports key with unsafe entries", () => {
  const compose = APPROVED_COMPOSE.replace(
    "  minio:",
    `${EXTRA_SERVICE_HEADER}    ports: # review this mapping\n      - "0.0.0.0:4321:4321"\n  minio:`,
  );
  assert.throws(() => verifyComposeText(compose));
});

test("rejects quoted unsafe MinIO images added to an unexpected service", () => {
  const compose = APPROVED_COMPOSE.replace(
    "  minio:",
    `  rogue-minio:\n    image: "minio/minio:edge"\n  minio:`,
  );
  assert.throws(() => verifyComposeText(compose));
});

test("rejects commented unsafe MinIO image lines added to an unexpected service", () => {
  const compose = APPROVED_COMPOSE.replace(
    "  minio:",
    `  rogue-minio:\n    image: "minio/minio:edge" # review this image\n  minio:`,
  );
  assert.throws(() => verifyComposeText(compose));
});

test("rejects YAML aliases and merge keys", () => {
  const compose = `defaults: &defaults
  image: pgvector/pgvector:pg16
services:
  postgres:
    <<: *defaults
    ports:
      - "127.0.0.1:5432:5432"
  minio:
    image: minio/minio:RELEASE.2024-06-13T22-53-53Z
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9001:9001"
volumes:
  tamforge-postgres:
  tamforge-minio:
`;
  assert.throws(() => verifyComposeText(compose));
});

test("rejects duplicate YAML keys", () => {
  const compose = APPROVED_COMPOSE.replace(
    `    ports:
      - "127.0.0.1:5432:5432"
`,
    `    ports:
      - "127.0.0.1:5432:5432"
    ports:
      - "127.0.0.1:5432:5432"
`,
  );
  assert.throws(() => verifyComposeText(compose));
});

test("rejects multiple YAML documents", () => {
  assert.throws(() => verifyComposeText(`${APPROVED_COMPOSE}\n---\nservices: {}`));
});

test("rejects malformed YAML", () => {
  assert.throws(() => verifyComposeText("services: ["));
});

test("rejects a wrong root shape", () => {
  assert.throws(() => verifyComposeText(APPROVED_COMPOSE.replace("services:", "service:")));
});

test("rejects missing or unexpected target services", () => {
  const missingMinio = APPROVED_COMPOSE.replace(/\n  minio:[\s\S]*?\nvolumes:/, "\nvolumes:");
  const unexpectedService = APPROVED_COMPOSE.replace(
    "  minio:",
    `${EXTRA_SERVICE_HEADER}  minio:`,
  );
  assert.throws(() => verifyComposeText(missingMinio));
  assert.throws(() => verifyComposeText(unexpectedService));
});
