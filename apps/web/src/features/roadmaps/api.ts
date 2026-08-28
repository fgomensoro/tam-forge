import type { components } from "../../api/schema";
import { apiRequest } from "../../api/client";

export type RoadmapImport = components["schemas"]["RoadmapImportResponse"];
export type RoadmapVersion = components["schemas"]["RoadmapVersionResponse"];

export type RoadmapPackage =
  | { kind: "zip"; file: File }
  | { kind: "folder_entries"; files: Array<{ file: File; path: string }> };

function idempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `roadmap-${Date.now()}`;
}

export function buildRoadmapForm(selection: RoadmapPackage) {
  const form = new FormData();
  form.append("package_kind", selection.kind);
  if (selection.kind === "zip") {
    form.append("package", selection.file, selection.file.name);
  } else {
    selection.files.forEach(({ file, path }) => {
      form.append("paths", path);
      form.append("files", file, file.name);
    });
  }
  return form;
}

export async function stageRoadmapPackage(selection: RoadmapPackage) {
  const form = buildRoadmapForm(selection);
  return apiRequest<RoadmapImport>("/api/v1/roadmap-imports", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey() },
    body: form,
  });
}

export function approveRoadmapImport(importId: number) {
  return apiRequest<RoadmapVersion>(`/api/v1/roadmap-imports/${importId}/approve`, {
    method: "POST",
  });
}

export function retryRoadmapMirror(versionId: number) {
  return apiRequest<RoadmapVersion>(`/api/v1/roadmap-imports/${versionId}/mirror/retry`, {
    method: "POST",
  });
}

export function activateRoadmapVersion(versionId: number) {
  return apiRequest<RoadmapVersion>(`/api/v1/roadmap-versions/${versionId}/activate`, {
    method: "POST",
  });
}

export function listRoadmapVersions() {
  return apiRequest<RoadmapVersion[]>("/api/v1/roadmap-versions");
}
