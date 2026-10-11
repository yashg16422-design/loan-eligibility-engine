// The one module that talks to the api Lambda. Same origin, so paths are relative.
import { auth } from "./auth";
import type {
  Account,
  Analytics,
  CatalogProduct,
  CrawlHealth,
  Match,
  Me,
  Preferences,
  Profile,
  Run,
  UploadProgress,
  UploadRecord,
  EmailPreview,
  WorkflowError,
} from "./types";

const TOKEN_KEY = "clickpe-match-token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: Record<string, unknown>, // the response body, for errors that carry data
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

async function request<T>(
  path: string,
  init: RequestInit = {},
  auth = false,
  account = false,
): Promise<{ status: number; body: T }> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("content-type", "application/json");
  if (account) {
    const id = await accountToken();
    if (!id) throw new ApiError(401, "Sign in to continue.");
    headers.set("authorization", `Bearer ${id}`); // verified by API Gateway's JWT authorizer
  }
  if (auth) {
    const token = session.get();
    if (!token) throw new ApiError(401, "Your link has expired. Run a new check to see your matches.");
    headers.set("authorization", `Bearer ${token}`);
  }
  const res = await fetchWithRetry(path, { ...init, headers });
  const body = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok)
    throw new ApiError(res.status, explain(res.status, body.error ?? (body as { message?: string }).message), body as Record<string, unknown>);
  return { status: res.status, body };
}

/** The server's sentence when it gave one; otherwise what the status means for the person. */
export function explain(status: number, message?: string): string {
  // API Gateway's own 401 says only "Unauthorized": say what to do instead.
  if (status === 401) return message && message !== "Unauthorized" ? message : "Your sign-in has expired. Sign in again to continue.";
  if (message) return message;
  if (status === 403) return "Your account is not allowed to do that.";
  if (status === 404) return "That item no longer exists.";
  if (status === 413) return "That file is too large: the limit is 50 MB.";
  if (status === 429) return "The daily limit is reached. Try again tomorrow.";
  if (status >= 500) return "The service had a problem. Try again in a moment.";
  return `The request failed (${status}). Try again.`;
}

// Reads (GET) are retried twice on a network error or a 5xx: one dropped request while polling
// must not fail a whole check. Writes are never retried, so nothing can be submitted twice.
const RETRY_DELAYS_MS = [700, 1800];

async function fetchWithRetry(path: string, init: RequestInit): Promise<Response> {
  const retryable = (init.method ?? "GET") === "GET";
  for (let attempt = 0; ; attempt++) {
    const last = !retryable || attempt >= RETRY_DELAYS_MS.length;
    try {
      const res = await fetch(path, init);
      if (res.status < 500 || last) return res;
    } catch (err) {
      if (last) throw new ApiError(0, "You seem to be offline. Check your connection and try again.");
    }
    await new Promise((r) => setTimeout(r, RETRY_DELAYS_MS[attempt]));
  }
}

const accountToken = () => auth.idToken();

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
  // Bulk uploads belong to the signed-in merchant: every /uploads call carries the ID token.
  createUpload: (filename: string) =>
    request<{ job_id: string; upload: { url: string; fields: Record<string, string> }; max_bytes: number }>(
      "/uploads",
      { method: "POST", body: JSON.stringify({ filename }) },
      false,
      true,
    ).then((r) => r.body),
  upload: (jobId: string) => request<UploadProgress>(`/uploads/${jobId}`, {}, false, true).then((r) => r.body),
  uploads: () => request<UploadRecord[]>("/uploads", {}, false, true).then((r) => r.body),
  cancelUpload: (jobId: string) =>
    request<{ job_id: string; outcome: "cancelled" | "running" | "finished" }>(
      `/uploads/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }, false, true,
    ).then((r) => r.body),
  emailPreviews: (jobId: string) => request<EmailPreview[]>(`/uploads/${jobId}/emails`, {}, false, true).then((r) => r.body),
  // Public: only the reference dataset. Signed in: one of my uploads (owner or admin), with the ID token.
  analytics: (jobId?: string | null) =>
    request<Analytics>(`/analytics${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""}`).then((r) => r.body),
  uploadAnalytics: (jobId: string) =>
    request<Analytics>(`/uploads/${encodeURIComponent(jobId)}/analytics`, {}, false, true).then((r) => r.body),
  account: () => request<Account>("/account", {}, false, true).then((r) => r.body),
  setDailyPicks: (daily_picks: boolean) =>
    request<Account>("/account", { method: "PUT", body: JSON.stringify({ daily_picks }) }, false, true).then((r) => r.body),
  saveProfile: (token: string) =>
    request<{ outcome: string; message: string; user_id: string }>(
      "/account/profiles",
      { method: "POST", body: JSON.stringify({ token }) },
      false,
      true,
    ).then((r) => r.body),
  openProfile: (userId: string) =>
    request<{ token: string }>(`/account/profiles/${userId}/open`, { method: "POST" }, false, true).then((r) => r.body),
  // Data reset. The account itself is never deleted by any of these.
  deleteMyCheck: () => request<{ outcome: string }>("/me", { method: "DELETE" }, true).then((r) => r.body),
  clearProfiles: (userId?: string) =>
    request<{ deleted_checks: number; unlinked: number }>(
      userId ? `/account/profiles/${userId}` : "/account/profiles",
      { method: "DELETE" },
      false,
      true,
    ).then((r) => r.body),
  /** Delete one upload's customers. A big upload is deleted in chunks: keep calling until
   *  nothing is left, reporting progress (each call stays well inside the API time limit). */
  purgeUpload: (jobId: string, onProgress?: Progress) =>
    untilDone((): Promise<Purged> =>
      request<Purged>(`/uploads/${jobId}`, { method: "DELETE" }, false, true).then((r) => r.body), onProgress),
  /** "mine" resets this account's workspace; "all" (admins) clears every account's uploads. */
  purgeUploads: (scope: "mine" | "all", onProgress?: Progress) =>
    untilDone((): Promise<Purged> =>
      request<Purged>(`/uploads?scope=${scope}`, { method: "DELETE" }, false, true).then((r) => r.body), onProgress),
};

type Purged = { deleted_users: number; remaining?: number; uploads?: number };
/** `waiting`: the upload is still sending its emails (409), so the delete is retried shortly. */
export type Progress = (deleted: number, remaining: number, waiting?: boolean) => void;

// A delete right after a run waits for its emails (the server says 409 for about two minutes)
// instead of failing: retried every 8 s for up to ~3 minutes.
const BUSY_RETRIES = 25;
const FAILED_RETRIES = 3;

/** Repeat a chunked delete until the server says nothing is left; totals across calls. */
export async function untilDone(
  call: () => Promise<Purged>,
  onProgress?: Progress,
  maxCalls = 200,
  busyPauseMs = 8000,
): Promise<Purged> {
  let deleted = 0;
  let uploads = 0;
  let busy = 0;
  let failed = 0;
  for (let i = 0; i < maxCalls; i++) {
    let r: Purged;
    try {
      r = await call();
    } catch (err) {
      // A cut-off call (gateway timeout, 5xx) rolled back its unfinished chunk, so calling
      // again is safe: it resumes where the last finished chunk stopped.
      if (err instanceof ApiError && (err.status >= 500 || err.status === 0) && ++failed <= FAILED_RETRIES) {
        await new Promise((ok) => setTimeout(ok, busyPauseMs / 4));
        continue;
      }
      if (!(err instanceof ApiError && err.status === 409) || ++busy > BUSY_RETRIES) throw err;
      onProgress?.(deleted, -1, true);
      await new Promise((ok) => setTimeout(ok, busyPauseMs));
      continue;
    }
    deleted += r.deleted_users;
    uploads += r.uploads ?? 0;
    const left = r.remaining ?? 0;
    onProgress?.(deleted, left);
    if (left === 0) return { deleted_users: deleted, remaining: 0, uploads };
  }
  throw new ApiError(504, "Deleting is taking unusually long. Run Delete again to continue where it stopped.");
}
