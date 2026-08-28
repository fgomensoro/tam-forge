import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useResumableTimer, type TimerTransport } from "../../src/features/activities/useResumableTimer";

beforeEach(() => localStorage.clear());

it("reuses one heartbeat sequence and idempotency key until the server acknowledges it", async () => {
  const heartbeat = vi.fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ optimistic_version: 2, open_timer: { last_client_sequence: 6 } });
  const transport = { heartbeat } as unknown as TimerTransport;
  const activity = {
    id: 41,
    state: "active",
    optimistic_version: 2,
    open_timer: { last_client_sequence: 5 },
  } as Parameters<typeof useResumableTimer>[0]["activity"];
  const first = renderHook(() => useResumableTimer({ activity, transport, onChange: vi.fn(), automatic: false }));

  await act(async () => { await first.result.current.heartbeatNow(); });
  first.unmount();
  const resumed = renderHook(() => useResumableTimer({ activity, transport, onChange: vi.fn(), automatic: false }));
  await act(async () => { await resumed.result.current.heartbeatNow(); });
  expect(heartbeat).toHaveBeenCalledTimes(2);
  expect(heartbeat.mock.calls[0]).toEqual(heartbeat.mock.calls[1]);
  expect(heartbeat.mock.calls[0][1].client_sequence).toBe(6);
  expect(localStorage.getItem("tamforge:activity:41:pending-timer")).toBeNull();
  resumed.unmount();
});
