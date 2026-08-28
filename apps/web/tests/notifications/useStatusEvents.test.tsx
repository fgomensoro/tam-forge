import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { expect, it, vi } from "vitest";
import { useStatusEvents } from "../../src/features/notifications/useStatusEvents";

function response(body: string) {
  return new Response(new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(body)); controller.close(); } }), { status: 200, headers: { "content-type": "text/event-stream" } });
}

it("reconnects from Last-Event-ID and invalidates affected queries", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response('id: 7\nevent: status\ndata: {"id":7,"event_type":"activity.feedback_ready","aggregate_type":"activity","aggregate_id":41,"subject_id":41,"related_id":null,"occurred_at":"2026-08-27T12:00:00Z"}\n\n'))
    .mockImplementation(() => new Promise(() => undefined));
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const statusEvent = vi.fn();
  window.addEventListener("tamforge:status", statusEvent);
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const hook = renderHook(() => useStatusEvents({ fetcher, retryDelayMs: 1, pollIntervalMs: 10_000 }), { wrapper });

  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(new Headers(fetcher.mock.calls[1][1]?.headers).get("Last-Event-ID")).toBe("7");
  expect(invalidate).toHaveBeenCalled();
  expect(statusEvent).toHaveBeenCalled();
  hook.unmount();
  window.removeEventListener("tamforge:status", statusEvent);
});

it("shows a disconnected fallback and keeps polling", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn().mockRejectedValue(new Error("offline"));
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const hook = renderHook(() => useStatusEvents({ fetcher, retryDelayMs: 10_000, pollIntervalMs: 1000 }), { wrapper });
  await act(async () => { await Promise.resolve(); });
  expect(hook.result.current.connection).toBe("disconnected");
  await act(async () => { vi.advanceTimersByTime(1000); });
  expect(invalidate).toHaveBeenCalled();
  hook.unmount();
  vi.useRealTimers();
});
