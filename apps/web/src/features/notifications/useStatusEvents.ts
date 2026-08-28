import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

type Connection = "connecting" | "live" | "disconnected";
type Fetcher = (...args: Parameters<typeof fetch>) => ReturnType<typeof fetch>;

interface StatusEvent {
  id: number;
  event_type: string;
  aggregate_type: string;
  aggregate_id: number;
  subject_id: number;
  related_id: number | null;
  occurred_at: string;
}

const CURSOR_KEY = "tamforge:last-status-event-id";

function readCursor() {
  try {
    const value = window.sessionStorage.getItem(CURSOR_KEY) ?? "";
    const parsed = Number(value);
    return /^\d+$/.test(value) && Number.isSafeInteger(parsed) && parsed >= 0 ? value : "";
  } catch { return ""; }
}

function saveCursor(cursor: string) {
  try { window.sessionStorage.setItem(CURSOR_KEY, cursor); } catch { /* A blocked session store must not stop updates. */ }
}

function parseBlock(block: string): { id: string; data: StatusEvent } | null {
  let id = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("id:")) id = line.slice(3).trim();
    if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!id || !data) return null;
  try {
    const parsed = JSON.parse(data) as StatusEvent;
    return Number.isSafeInteger(parsed.id) && String(parsed.id) === id ? { id, data: parsed } : null;
  } catch { return null; }
}

function wait(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { window.clearTimeout(timer); resolve(); }, { once: true });
  });
}

export function useStatusEvents({
  fetcher = window.fetch.bind(window),
  retryDelayMs = 3_000,
  pollIntervalMs = 30_000,
}: { fetcher?: Fetcher; retryDelayMs?: number; pollIntervalMs?: number } = {}) {
  const queryClient = useQueryClient();
  const [connection, setConnection] = useState<Connection>("connecting");
  const connectionRef = useRef<Connection>("connecting");

  useEffect(() => { connectionRef.current = connection; }, [connection]);

  useEffect(() => {
    const poll = window.setInterval(() => {
      if (connectionRef.current !== "disconnected") return;
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
      void queryClient.invalidateQueries({ queryKey: ["today"] });
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-judgment"] });
    }, pollIntervalMs);
    return () => window.clearInterval(poll);
  }, [pollIntervalMs, queryClient]);

  useEffect(() => {
    const controller = new AbortController();
    let cursor = readCursor();

    const refresh = (event: StatusEvent) => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
      void queryClient.invalidateQueries({ queryKey: ["today"] });
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-judgment"] });
      window.dispatchEvent(new CustomEvent("tamforge:status", { detail: { query: "all", event } }));
    };

    const connect = async () => {
      while (!controller.signal.aborted) {
        try {
          const headers = new Headers({ Accept: "text/event-stream" });
          if (cursor) headers.set("Last-Event-ID", cursor);
          const response = await fetcher("/api/v1/events", { headers, credentials: "include", signal: controller.signal });
          if (!response.ok || !response.body) throw new Error("status stream unavailable");
          setConnection("live");
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!controller.signal.aborted) {
            const result = await reader.read();
            if (result.done) break;
            buffer += decoder.decode(result.value, { stream: true });
            buffer = buffer.replaceAll("\r\n", "\n");
            const blocks = buffer.split("\n\n");
            buffer = blocks.pop() ?? "";
            for (const block of blocks) {
              const event = parseBlock(block);
              if (!event) continue;
              cursor = event.id;
              saveCursor(cursor);
              refresh(event.data);
            }
          }
          if (!controller.signal.aborted) {
            setConnection("disconnected");
            await wait(retryDelayMs, controller.signal);
            if (!controller.signal.aborted) setConnection("connecting");
          }
        } catch {
          if (controller.signal.aborted) break;
          setConnection("disconnected");
          await wait(retryDelayMs, controller.signal);
          if (!controller.signal.aborted) setConnection("connecting");
        }
      }
    };

    void connect();
    return () => controller.abort();
  }, [fetcher, queryClient, retryDelayMs]);

  return { connection };
}
