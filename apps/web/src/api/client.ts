import { z } from "zod";

const problemSchema = z.object({
  type: z.string().optional(),
  title: z.string().optional(),
  status: z.number().optional(),
  detail: z.string().optional(),
  code: z.string().optional(),
});

export type ApiProblem = z.infer<typeof problemSchema>;

export class ApiProblemError extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly type: string;

  constructor(problem: ApiProblem, responseStatus: number) {
    super(problem.detail || problem.title || "The request could not be completed.");
    this.name = "ApiProblemError";
    this.status = problem.status ?? responseStatus;
    this.code = problem.code ?? "request_failed";
    this.title = problem.title ?? "Request failed";
    this.type = problem.type ?? "about:blank";
  }
}

let csrfToken: string | null = null;
const unauthorizedHandlers = new Set<() => void>();

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function registerUnauthorizedHandler(handler: () => void) {
  unauthorizedHandlers.add(handler);
  return () => {
    unauthorizedHandlers.delete(handler);
  };
}

function apiUrl(path: string) {
  if (/^https?:\/\//u.test(path)) return path;
  return new URL(path, window.location.origin).toString();
}

function isMutation(method = "GET") {
  return !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
}

async function readProblem(response: Response): Promise<ApiProblem> {
  try {
    const parsed = problemSchema.safeParse(await response.json());
    if (parsed.success) return parsed.data;
  } catch {
    // A non-JSON upstream error is intentionally reduced to a generic problem.
  }
  return { status: response.status, title: "Request failed", code: "request_failed" };
}

export async function apiRequest<T = unknown>(
  path: string,
  init: Parameters<typeof fetch>[1] = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (isMutation(init.method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);

  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    if (response.status === 401) unauthorizedHandlers.forEach((handler) => handler());
    throw new ApiProblemError(await readProblem(response), response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
