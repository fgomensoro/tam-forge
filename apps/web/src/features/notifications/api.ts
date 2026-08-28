import type { components } from "../../api/schema";
import { apiRequest } from "../../api/client";

export type NotificationPage = components["schemas"]["NotificationPage"];
export type Notification = components["schemas"]["NotificationResponse"];

export const notificationTypes = [
  "feedback_ready",
  "correction_due",
  "upcoming_real_interview",
  "saturday_assessment",
  "processing_failure_requires_action",
] as const;

export function isAllowedNotification(value: string): value is Notification["notification_type"] {
  return (notificationTypes as readonly string[]).includes(value);
}

export function getNotifications() {
  return apiRequest<NotificationPage>("/api/v1/notifications?limit=100");
}

export function markNotificationRead(notificationId: number) {
  return apiRequest<Notification>(`/api/v1/notifications/${notificationId}/read`, { method: "POST" });
}
