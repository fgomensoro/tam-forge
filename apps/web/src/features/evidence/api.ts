import type { components } from "../../api/schema";
import { apiRequest } from "../../api/client";

export type SkillList = components["schemas"]["SkillListResponse"];
export type SkillSummary = components["schemas"]["SkillSummaryResponse"];
export type SkillSnapshot = components["schemas"]["SkillSnapshotResponse"];
export type SnapshotManifestItem = components["schemas"]["SnapshotManifestItem"];
export type EvidenceEvent = components["schemas"]["EvidenceEventResponse"];
export type EvidenceEventPage = components["schemas"]["EvidenceEventPage"];
export type PortfolioHistory = components["schemas"]["PortfolioHistoryResponse"];
export type PortfolioScore = components["schemas"]["PortfolioScoreResponse"];

export function getSkills() {
  return apiRequest<SkillList>("/api/v1/skills");
}

export function getSkillEvidence(skillSlug: string) {
  return apiRequest<EvidenceEventPage>(`/api/v1/skills/${encodeURIComponent(skillSlug)}/evidence?limit=100`);
}

export function getActivityEvidence(activityId: number) {
  return apiRequest<EvidenceEventPage>(`/api/v1/activities/${activityId}/evidence?limit=100`);
}

export function getPortfolioHistory() {
  return apiRequest<PortfolioHistory>("/api/v1/portfolio-judgment?limit=100");
}
