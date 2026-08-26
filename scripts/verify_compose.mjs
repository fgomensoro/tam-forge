import YAML from "yaml";

const APPROVED_MINIO_IMAGE = "minio/minio:RELEASE.2024-06-13T22-53-53Z";
const APPROVED_COMPOSE = {
  services: {
    postgres: {
      image: "pgvector/pgvector:pg16",
      environment: {
        POSTGRES_DB: "tamforge",
        POSTGRES_USER: "tamforge",
        POSTGRES_PASSWORD: "tamforge",
      },
      ports: ["127.0.0.1:54329:5432"],
      volumes: ["tamforge-postgres:/var/lib/postgresql/data"],
    },
    minio: {
      image: APPROVED_MINIO_IMAGE,
      command: 'server /data --console-address ":9001"',
      environment: {
        MINIO_ROOT_USER: "tamforge",
        MINIO_ROOT_PASSWORD: "tamforge-local",
      },
      ports: ["127.0.0.1:9000:9000", "127.0.0.1:9001:9001"],
      volumes: ["tamforge-minio:/data"],
    },
  },
  volumes: {
    "tamforge-postgres": null,
    "tamforge-minio": null,
  },
};

function rejectUnsupportedNodes(node, seen = new Set()) {
  if (node === null || typeof node !== "object" || seen.has(node)) return;
  seen.add(node);

  if (node.constructor?.name === "Alias" || node.type === "ALIAS") {
    throw new Error("YAML aliases are not supported");
  }
  if (node.anchor || node.tag) {
    throw new Error("YAML anchors and custom tags are not supported");
  }

  if (Array.isArray(node.items)) {
    for (const item of node.items) rejectUnsupportedNodes(item, seen);
  }
  if ("key" in node) rejectUnsupportedNodes(node.key, seen);
  if ("value" in node) rejectUnsupportedNodes(node.value, seen);
}

function isPlainRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertSameStructure(actual, expected, path) {
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || actual.length !== expected.length) {
      throw new Error(`unexpected ${path}; expected the approved mapping`);
    }
    expected.forEach((value, index) => assertSameStructure(actual[index], value, `${path}[${index}]`));
    return;
  }

  if (isPlainRecord(expected)) {
    if (!isPlainRecord(actual)) {
      throw new Error(`unexpected ${path}; expected a mapping`);
    }
    const expectedKeys = Object.keys(expected).sort();
    const actualKeys = Object.keys(actual).sort();
    if (
      expectedKeys.length !== actualKeys.length ||
      expectedKeys.some((key, index) => key !== actualKeys[index])
    ) {
      throw new Error(`unexpected keys at ${path}; expected the approved mapping`);
    }
    for (const key of expectedKeys) assertSameStructure(actual[key], expected[key], `${path}.${key}`);
    return;
  }

  if (actual !== expected) {
    throw new Error(`unexpected ${path}; expected the approved value`);
  }
}

export function verifyComposeText(compose) {
  let documents;
  try {
    documents = YAML.parseAllDocuments(compose, {
      version: "1.2",
      uniqueKeys: true,
      stringKeys: true,
    });
  } catch (error) {
    throw new Error("Compose YAML could not be parsed", { cause: error });
  }

  if (documents.length !== 1) {
    throw new Error("exactly one Compose YAML document is required");
  }

  const [document] = documents;
  if (document.errors.length > 0 || document.warnings.length > 0) {
    throw new Error("Compose YAML contains parse errors or warnings", {
      cause: document.errors[0] ?? document.warnings[0],
    });
  }
  rejectUnsupportedNodes(document.contents);

  let parsed;
  try {
    parsed = document.toJS({ mapAsMap: false });
  } catch (error) {
    throw new Error("Compose YAML could not be materialized safely", { cause: error });
  }
  assertSameStructure(parsed, APPROVED_COMPOSE, "Compose document");

  return {
    publishedPorts: [...APPROVED_COMPOSE.services.postgres.ports, ...APPROVED_COMPOSE.services.minio.ports],
    minioImage: APPROVED_MINIO_IMAGE,
  };
}
