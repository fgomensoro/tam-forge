import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

import { verifyComposeText } from "./verify_compose.mjs";

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

if (
  allowBuilds?.esbuild !== true ||
  allowBuilds?.msw !== false ||
  Object.keys(allowBuilds).length !== 2
) {
  throw new Error("pnpm must allow only esbuild and explicitly deny the optional MSW script");
}

const compose = readFileSync("compose.dev.yml", "utf8");
const { publishedPorts } = verifyComposeText(compose);

console.log(`Bootstrap tooling verified: pnpm@${runningVersion}; ports=${publishedPorts.join(", ")}`);
