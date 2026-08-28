import { useCallback, useEffect, useMemo, useState } from "react";
import {
  heartbeatActivity,
  pauseActivity,
  resumeActivity,
  startActivity,
  type ActivityResponse,
} from "./api";

export interface TimerActivity {
  id: number;
  state: string;
  optimistic_version: number;
  open_timer: null | { last_client_sequence: number };
}

interface TimerCommand { expected_version: number; client_sequence: number }
interface VersionCommand { expected_version: number }
export interface TimerTransport {
  start(id: number, command: VersionCommand, key: string): Promise<ActivityResponse>;
  pause(id: number, command: TimerCommand, key: string): Promise<ActivityResponse>;
  resume(id: number, command: VersionCommand, key: string): Promise<ActivityResponse>;
  heartbeat(id: number, command: TimerCommand, key: string): Promise<ActivityResponse>;
}

const transportDefault: TimerTransport = {
  start: (id, value, key) => startActivity(id, value.expected_version, key),
  pause: (id, value, key) => pauseActivity(id, value.expected_version, value.client_sequence, key),
  resume: (id, value, key) => resumeActivity(id, value.expected_version, key),
  heartbeat: (id, value, key) => heartbeatActivity(id, value.expected_version, value.client_sequence, key),
};

function key(activityId: number) { return `tamforge:activity:${activityId}:pending-timer`; }
function idempotency(scope: string, id: number) { return `${scope}-${id}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`; }
function readPending(id: number): { client_sequence: number; idempotency_key: string } | null {
  try {
    const raw = localStorage.getItem(key(id));
    return raw ? JSON.parse(raw) as { client_sequence: number; idempotency_key: string } : null;
  } catch { return null; }
}

export function useResumableTimer({
  activity,
  onChange,
  transport = transportDefault,
  automatic = true,
}: {
  activity: TimerActivity;
  onChange: (activity: ActivityResponse) => void;
  transport?: TimerTransport;
  automatic?: boolean;
}) {
  const [syncIssue, setSyncIssue] = useState(false);

  const nextSequence = useCallback(() => {
    const server = activity.open_timer?.last_client_sequence ?? 0;
    const pending = readPending(activity.id)?.client_sequence ?? 0;
    return Math.max(server, pending) + 1;
  }, [activity.id, activity.open_timer?.last_client_sequence]);

  const heartbeatNow = useCallback(async () => {
    if (activity.state !== "active") return;
    const pending = readPending(activity.id) ?? {
      client_sequence: nextSequence(),
      idempotency_key: idempotency("heartbeat", activity.id),
    };
    localStorage.setItem(key(activity.id), JSON.stringify(pending));
    try {
      const response = await transport.heartbeat(activity.id, {
        expected_version: activity.optimistic_version,
        client_sequence: pending.client_sequence,
      }, pending.idempotency_key);
      localStorage.removeItem(key(activity.id));
      setSyncIssue(false);
      onChange(response);
    } catch {
      setSyncIssue(true);
    }
  }, [activity.id, activity.optimistic_version, activity.state, nextSequence, onChange, transport]);

  useEffect(() => {
    if (!automatic || activity.state !== "active") return;
    const interval = window.setInterval(() => { void heartbeatNow(); }, 15_000);
    return () => window.clearInterval(interval);
  }, [activity.state, automatic, heartbeatNow]);

  return useMemo(() => ({
    syncIssue,
    heartbeatNow,
    nextSequence,
    start: async () => {
      const response = await transport.start(activity.id, { expected_version: activity.optimistic_version }, idempotency("start", activity.id));
      onChange(response);
    },
    pause: async () => {
      const response = await transport.pause(activity.id, { expected_version: activity.optimistic_version, client_sequence: nextSequence() }, idempotency("pause", activity.id));
      localStorage.removeItem(key(activity.id));
      onChange(response);
    },
    resume: async () => {
      const response = await transport.resume(activity.id, { expected_version: activity.optimistic_version }, idempotency("resume", activity.id));
      onChange(response);
    },
  }), [activity.id, activity.optimistic_version, heartbeatNow, nextSequence, onChange, syncIssue, transport]);
}
