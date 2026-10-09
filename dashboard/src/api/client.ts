// The one module that talks to the api Lambda. Same origin, so paths are relative.
import type {
  CatalogProduct,
  CrawlHealth,
  Match,
  Me,
  Preferences,
  Profile,
  Run,
  UploadProgress,
  WorkflowError,
} from "./types";

const TOKEN_KEY = "clickpe-match-token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

// Session storage only: the token is a short-lived bearer credential, never persisted.
export const session = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string) {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* private mode: the token still lives in memory for this page */
    }
  },
  clear() {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing to clear */
    }
  },
};

/** A token arriving in the email link (?t=...) is moved into the session and off the URL. */
export function adoptTokenFromUrl(): void {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("t");
  if (!token) return;
  session.set(token);
  url.searchParams.delete("t");
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
}

async function request<T>(path: string, init: RequestInit = {}, auth = false): Promise<{ status: number; body: T }> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("content-type", "application/json");
  if (auth) {
    const token = session.get();
    if (!token) throw new ApiError(401, "Your link has expired. Run a new check to see your matches.");
    headers.set("authorization", `Bearer ${token}`);
  }
  const res = await fetch(path, { ...init, headers });
  const body = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) throw new ApiError(res.status, body.error ?? `Request failed (${res.status})`);
  return { status: res.status, body };
}

export const api = {
  check: (profile: Profile & { name?: string }) =>
    request<{ token: string; user_id: string; job_id: string }>("/check", {
      method: "POST",
      body: JSON.stringify(profile),
    }).then((r) => r.body),
  me: () => request<Me | { matching: "queued" }>("/me", {}, true),
  matches: () => request<Match[]>("/me/matches", {}, true).then((r) => r.body),
  preferences: () => request<Preferences>("/me/preferences", {}, true).then((r) => r.body),
  savePreferences: (prefs: Omit<Preferences, "updated_at">) =>
    request<Preferences>("/me/preferences", { method: "PUT", body: JSON.stringify(prefs) }, true).then((r) => r.body),
  products: () => request<CatalogProduct[]>("/products").then((r) => r.body),
  runs: () => request<Run[]>("/ops/runs").then((r) => r.body),
  crawl: () => request<CrawlHealth>("/ops/crawl").then((r) => r.body),
  errors: () => request<WorkflowError[]>("/ops/errors").then((r) => r.body),
  createUpload: (filename: string) =>
    request<{ job_id: string; upload: { url: string; fields: Record<string, string> }; max_bytes: number }>(
      "/uploads",
      { method: "POST", body: JSON.stringify({ filename }) },
    ).then((r) => r.body),
  upload: (jobId: string) => request<UploadProgress>(`/uploads/${jobId}`).then((r) => r.body),
};
