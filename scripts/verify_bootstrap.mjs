import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const packageManifest = JSON.parse(readFileSync("package.json", "utf8"));
const declaredPackageManager = packageManifest.packageManager;
const [declaredName, declaredVersion] = declaredPackageManager.split("@");
const runningVersion = execFileSync("pnpm", ["--version"], { encoding: "utf8" }).trim();

if (declaredName !== "pnpm" || declaredVersion !== runningVersion) {
  throw new Error(
    `packageManager must match the approved runtime: declared ${declaredPackageManager}, running pnpm@${runningVersion}`,
  );
}

const allowBuilds = JSON.parse(
  execFileSync("pnpm", ["config", "get", "allowBuilds"], { encoding: "utf8" }),
);

if (allowBuilds?.esbuild !== true || Object.keys(allowBuilds).length !== 1) {
  throw new Error("pnpm must recognize the explicit esbuild build allowlist");
}

const compose = readFileSync("compose.dev.yml", "utf8");
const publishedPorts = [
  ...compose.matchAll(/^\s*-\s+["']?((?:[\d.]+:)?\d{1,5}:\d{1,5})["']?\s*$/gm),
].map((match) => match[1]);

if (publishedPorts.length === 0 || publishedPorts.some((port) => !port.startsWith("127.0.0.1:"))) {
  throw new Error(`every published development port must bind to 127.0.0.1: ${publishedPorts.join(", ")}`);
}

if (compose.includes("minio/minio:latest")) {
  throw new Error("the local MinIO image must use an immutable release tag");
}

console.log(`Bootstrap tooling verified: pnpm@${runningVersion}; ports=${publishedPorts.join(", ")}`);
