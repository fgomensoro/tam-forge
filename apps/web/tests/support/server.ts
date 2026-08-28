import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

export const server = setupServer(
  http.get("*/api/v1/notifications", () => HttpResponse.json({ items: [], next_cursor: null })),
  http.get("*/api/v1/events", () => new HttpResponse(": keepalive\n\n", { headers: { "content-type": "text/event-stream" } })),
);
