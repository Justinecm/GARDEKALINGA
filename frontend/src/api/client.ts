// Small fetch wrapper: same-origin, cookie session, CSRF header on unsafe methods,
// one error shape ({"error": {"code", "message", "fields"}}).
let csrfToken: string | null = null;
let onReauth: (() => Promise<boolean>) | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrf(token: string | null) {
  csrfToken = token;
}
export function setReauthHandler(fn: (() => Promise<boolean>) | null) {
  onReauth = fn;
}
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;
  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

async function request<T>(method: string, path: string, body?: unknown, retried = false): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "network", "No connection. Check your mobile data or Wi-Fi.");
  }
  if (res.ok) {
    const type = res.headers.get("content-type") ?? "";
    return (type.includes("application/json") ? await res.json() : await res.text()) as T;
  }
  let err: { code?: string; message?: string; fields?: Record<string, string> } = {};
  try {
    err = ((await res.json()) as { error?: typeof err }).error ?? {};
  } catch {
    /* not JSON */
  }
  const e = new ApiError(res.status, err.code ?? "http_" + res.status, err.message ?? res.statusText, err.fields ?? {});
  if (e.code === "reauth_required" && onReauth && !retried) {
    if (await onReauth()) return request<T>(method, path, body, true);
  }
  if (res.status === 401 && e.code === "not_authenticated" && onUnauthorized) onUnauthorized();
  throw e;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
};

export function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? "?" + s : "";
}
