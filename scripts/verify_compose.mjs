const APPROVED_PORT_ENTRIES = [
  '"127.0.0.1:5432:5432"',
  '"127.0.0.1:9000:9000"',
  '"127.0.0.1:9001:9001"',
];
const APPROVED_MINIO_IMAGE = "minio/minio:RELEASE.2024-06-13T22-53-53Z";

function extractPortEntries(compose) {
  const entries = [];
  let inPortsBlock = false;
  let portsIndent = -1;

  for (const line of compose.split(/\r?\n/)) {
    const trimmed = line.trim();
    const indent = line.length - line.trimStart().length;

    if (!inPortsBlock) {
      if (trimmed === "ports:") {
        inPortsBlock = true;
        portsIndent = indent;
      }
      continue;
    }

    if (trimmed && indent <= portsIndent) {
      inPortsBlock = false;
      continue;
    }
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (!trimmed.startsWith("-")) {
      throw new Error("unsupported ports representation; only exact short syntax is allowed");
    }
    entries.push(trimmed.slice(1).trim());
  }

  return entries;
}

export function verifyComposeText(compose) {
  const portEntries = extractPortEntries(compose);
  const hasApprovedPorts =
    portEntries.length === APPROVED_PORT_ENTRIES.length &&
    APPROVED_PORT_ENTRIES.every((entry, index) => portEntries[index] === entry);

  if (!hasApprovedPorts) {
    throw new Error(
      `unsupported published ports; expected only ${APPROVED_PORT_ENTRIES.join(", ")}`,
    );
  }

  const imageReferences = [
    ...compose.matchAll(/^\s*image:\s*([^\s#]+)\s*$/gm),
  ].map((match) => match[1]);
  const minioImages = imageReferences.filter((image) => image.startsWith("minio/minio"));

  if (minioImages.length !== 1 || minioImages[0] !== APPROVED_MINIO_IMAGE) {
    throw new Error(`unsupported MinIO image; expected exactly ${APPROVED_MINIO_IMAGE}`);
  }

  return {
    publishedPorts: portEntries.map((entry) => entry.slice(1, -1)),
    minioImage: minioImages[0],
  };
}
