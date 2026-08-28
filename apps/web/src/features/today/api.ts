import type { components } from "../../api/schema";
import { apiRequest } from "../../api/client";

export type Today = components["schemas"]["TodayResponse"];
export type TodayTask = components["schemas"]["TodayTaskCard"];
export type TodayContinue = components["schemas"]["ContinueAction"];
export type DailyCloseCommand = components["schemas"]["DailyCloseCommand"];
export type DailyCloseResponse = components["schemas"]["DailyCloseResponse"];

export function localIsoDate(now = new Date()) {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function getToday(localDate = localIsoDate()) {
  return apiRequest<Today>(`/api/v1/today?date=${encodeURIComponent(localDate)}`);
}

export function closeToday(localDate: string, command: DailyCloseCommand) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`;
  return apiRequest<DailyCloseResponse>(`/api/v1/today/${localDate}/close`, {
    method: "POST",
    headers: { "Idempotency-Key": `daily-close-${localDate}-${suffix}` },
    body: JSON.stringify(command),
  });
}
