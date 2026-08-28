import type { components } from "../../api/schema";
import { apiRequest } from "../../api/client";

export type OutputKind = "reading" | "sql" | "case" | "writing" | "pipeline";
export type ActivityResponse = components["schemas"]["ActivityResponse"];
export type ActivityDetail = components["schemas"]["ActivityDetailResponse"];
export type ArtifactReference = components["schemas"]["ArtifactReference"];
export interface SelfReviewInput { main_answer: string; did_well: string; structure_weakness: string; vague_points: string; hesitation_points: string; change_next: string; self_score: number }
export const MAX_BROWSER_ARTIFACT_BYTES = 25 * 1024 * 1024;

function commandKey(scope: string, activityId: number) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${scope}-${activityId}-${suffix}`;
}

function command<T>(activityId: number, action: string, body: object, idempotencyKey = commandKey(action, activityId)) {
  return apiRequest<T>(`/api/v1/activities/${activityId}/${action}`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(body),
  });
}

export const getActivity = (id: number) => apiRequest<ActivityDetail>(`/api/v1/activities/${id}`);
export const startActivity = (id: number, expected_version: number, key = commandKey("start", id)) => command<ActivityResponse>(id, "start", { expected_version }, key);
export const pauseActivity = (id: number, expected_version: number, client_sequence: number, key = commandKey("pause", id)) => command<ActivityResponse>(id, "pause", { expected_version, client_sequence }, key);
export const resumeActivity = (id: number, expected_version: number, key = commandKey("resume", id)) => command<ActivityResponse>(id, "resume", { expected_version }, key);
export const heartbeatActivity = (id: number, expected_version: number, client_sequence: number, key: string) => command<ActivityResponse>(id, "heartbeat", { expected_version, client_sequence }, key);
export const setSourceVisibility = (id: number, expected_version: number, hidden: boolean) => command<ActivityDetail>(id, "source-visibility", { expected_version, hidden });

export function commitOutput(id: number, expected_version: number, client_sequence: number, output: Record<string, unknown>, artifact_refs: ArtifactReference[]) {
  return command(id, "commit-output", { expected_version, client_sequence, output, artifact_refs });
}

export function submitSelfReview(id: number, expected_version: number, review: SelfReviewInput) {
  return command(id, "self-review", { expected_version, ...review });
}

export async function uploadArtifact(id: number, expectedVersion: number, file: File, artifactClass: string) {
  if (file.size > MAX_BROWSER_ARTIFACT_BYTES) throw new Error("Supporting artifacts must be 25 MB or smaller.");
  const bytes = await file.arrayBuffer();
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((value) => value.toString(16).padStart(2, "0")).join("");
  const uploadKey = commandKey("artifact-upload", id);
  const presigned = await command<{ object_key: string; reused: boolean; upload: null | { url: string; method: "PUT"; headers: Record<string, string> } }>(id, "artifacts/presign", {
    expected_version: expectedVersion,
    artifact_class: artifactClass,
    sha256: digest,
    byte_length: file.size,
    content_type: file.type || "application/octet-stream",
    original_filename: file.name,
  }, uploadKey);
  if (!presigned.reused && presigned.upload) {
    const response = await fetch(presigned.upload.url, { method: "PUT", headers: presigned.upload.headers, body: file });
    if (!response.ok) throw new Error("The artifact upload failed before confirmation.");
  }
  return command<{ id: number; original_filename: string; artifact_class: string }>(id, "artifacts/confirm", {
    expected_version: expectedVersion,
    upload_idempotency_key: uploadKey,
    object_key: presigned.object_key,
  });
}
