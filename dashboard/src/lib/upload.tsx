// Bulk CSV upload, available from every page (the header button). One upload at a time;
// progress comes from GET /uploads/{job_id} (the same endpoint the original upload page uses).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { UploadProgress } from "../api/types";
import { UploadBlockedDialog } from "../components/UploadBlockedDialog";
import { navigate } from "../router";

export const MAX_BYTES = 50 * 1024 * 1024; // same limit the S3 upload policy enforces

export type UploadState =
  | { phase: "idle" }
  | { phase: "sending"; name: string; bytes: number }
  | {
      phase: "tracking";
      name: string;
      bytes: number;
      jobId: string;
      progress?: UploadProgress;
      finished: boolean;
      startedAt: number; // epoch ms, for the "while you wait" timer
      reconnecting?: boolean; // the last poll failed transiently; still tracking
    }
  | { phase: "error"; name?: string; message: string }
  // The account's earlier upload is still running or still holds customers (server said 409).
  | { phase: "blocked"; name: string; bytes: number; blocking: Blocking }
  // cleaning: Stop is still clearing the upload's records (matching had to finish first).
  | { phase: "stopped"; name: string; message: string; cleaning?: boolean };

/** What blocks a new upload: the account's one live upload (see POST /uploads, 409). */
export type Blocking = {
  job_id: string;
  filename: string | null;
  stage: "loading" | "matching" | "emailing" | "stored";
  customers: number;
};

interface Ctx {
  state: UploadState;
  pick: () => void;
  reset: () => void;
  stop: () => Promise<void>;
}

/** Nothing new can start: a file is going up, a run is tracked, or Stop is still clearing. */
export function isBusy(s: UploadState): boolean {
  return s.phase === "sending" || (s.phase === "tracking" && !s.finished) || (s.phase === "stopped" && !!s.cleaning);
}

/** What Stop did, in words (server outcome -> sentence). */
export function stopMessage(outcome: string): string {
  if (outcome === "cancelled") return "Stopped. The file was never loaded, so nothing was matched or emailed.";
  if (outcome === "cleared")
    return "Stopped and cleaned up: its customers, matches and email records are deleted. The run history stays.";
  if (outcome === "running")
    return "Stopping. Matching was already running on the server; it finishes in a minute or two, then this upload's records are deleted.";
  return "This upload had already finished. Delete it below if you want its customers removed.";
}

const n = (v: number) => new Intl.NumberFormat("en-IN").format(v);
const pause = (ms: number) => new Promise((ok) => setTimeout(ok, ms));

/** Wait until an upload can no longer change (failed, or matched and emailed). */
export async function settle(jobId: string, pollMs = 4000, limitMs = 8 * 60_000): Promise<void> {
  const until = Date.now() + limitMs;
  while (Date.now() < until) {
    try {
      if (isFinished(await api.upload(jobId))) return;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return; // gone: nothing to wait for
      // anything else is a blip while polling: keep waiting
    }
    await pause(pollMs);
  }
  throw new ApiError(504, "It is still running after 8 minutes. The server recovers stuck runs by itself; try again in a few minutes.");
}

/**
 * Clear an upload completely, so the account can start again: stop it (a file not yet loaded
 * is cancelled; a stuck run is ended), let a running match finish, then delete its records.
 * `outcome` skips the stop call when the caller already made it.
 */
export async function clearUpload(jobId: string, onStatus: (s: string) => void, outcome?: string): Promise<void> {
  if (!outcome) {
    onStatus("Stopping it…");
    outcome = (await api.cancelUpload(jobId)).outcome;
  }
  if (outcome === "running") {
    onStatus("It is matching on the server and finishes on its own, usually within two minutes. Waiting…");
    await settle(jobId);
  }
  onStatus("Deleting its records…");
  await api.purgeUpload(jobId, (deleted, left, waiting) =>
    onStatus(waiting ? "Waiting for its emails to finish…" : left > 0 ? `Deleting… ${n(deleted)} done, ${n(left)} to go.` : "Deleted."),
  );
}

const UploadContext = createContext<Ctx | null>(null);

/** True once nothing more can change: failed, or matched and emails handled (or nothing new). */
export function isFinished(p: UploadProgress | undefined): boolean {
  if (!p) return false;
  const j = p.job;
  if (j.status === "FAILED" || j.status === "EXPIRED" || j.match_status === "FAILED") return true;
  if (j.match_status !== "DONE" || !p.match_run) return false;
  const handled = Object.values(p.notifications ?? {}).reduce((a, b) => a + b, 0) > 0;
  return handled || !p.match_run.matches_new; // nothing new = nobody to email
}

// The upload being tracked survives a reload (this tab only): the pipeline runs on the server
// either way, so the page just picks the job up again.
const KEY = "clickpar-upload";
type Saved = { jobId: string; name: string; bytes: number; startedAt: number };

function saved(): Saved | null {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? "null") as Saved | null;
  } catch {
    return null;
  }
}

function remember(s: Saved | null) {
  try {
    if (s) sessionStorage.setItem(KEY, JSON.stringify(s));
    else sessionStorage.removeItem(KEY);
  } catch {
    /* private mode: tracking just lasts for this page */
  }
}

/** Initial state: resume a tracked upload after a reload. */
export function resumed(): UploadState {
  const s = saved();
  return s ? { phase: "tracking", ...s, finished: false } : { phase: "idle" };
}

export function UploadProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<UploadState>(resumed);
  const input = useRef<HTMLInputElement>(null);
  const pending = useRef<File | null>(null); // the file waiting while an earlier upload is cleared

  useEffect(() => {
    if (state.phase !== "tracking") return;
    if (state.finished) {
      remember(null);
      return;
    }
    // Faster while there is a lot to watch, gentler while reconnecting.
    const id = window.setTimeout(async () => {
      try {
        const progress = await api.upload(state.jobId);
        setState((s) =>
          s.phase === "tracking" ? { ...s, progress, finished: isFinished(progress), reconnecting: false } : s,
        );
      } catch (err) {
        // Signed out / no longer yours: stop and say so. Anything else (a timeout while the
        // database is busy, a network blip) is transient: keep tracking and say "reconnecting".
        if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
          remember(null);
          setState((s) => (s.phase === "tracking" ? { phase: "error", name: s.name, message: err.message } : s));
        } else {
          setState((s) => (s.phase === "tracking" ? { ...s, reconnecting: true } : s));
        }
      }
    }, state.reconnecting ? 4000 : 1500);
    return () => window.clearTimeout(id);
  }, [state]);

  const start = useCallback(async (file: File) => {
    navigate("merchant");
    setState({ phase: "sending", name: file.name, bytes: file.size });
    try {
      // Checked here first, so a wrong file never costs an upload ticket.
      if (!/\.csv$/i.test(file.name)) throw new ApiError(400, "This is not a CSV file. Choose a .csv file.");
      if (file.size === 0) throw new ApiError(400, "That file is empty.");
      if (file.size > MAX_BYTES) throw new ApiError(413, `That file is ${(file.size / 1048576).toFixed(1)} MB; the limit is 50 MB.`);
      let ticket;
      try {
        ticket = await api.createUpload(file.name);
      } catch (err) {
        const blocking = err instanceof ApiError && err.status === 409 ? (err.detail?.blocking as Blocking | undefined) : undefined;
        if (!blocking) throw err;
        pending.current = file;
        setState({ phase: "blocked", name: file.name, bytes: file.size, blocking });
        return;
      }
      if (file.size > ticket.max_bytes) throw new ApiError(413, "That file is larger than 50 MB.");
      const form = new FormData();
      Object.entries(ticket.upload.fields).forEach(([k, v]) => form.append(k, v));
      form.append("file", new Blob([file], { type: "text/csv" }), file.name);
      const res = await fetch(ticket.upload.url, { method: "POST", body: form });
      if (!res.ok) throw new ApiError(res.status, "Storage refused the file. Check it is a CSV under 50 MB.");
      const track = { jobId: ticket.job_id, name: file.name, bytes: file.size, startedAt: Date.now() };
      remember(track);
      setState({ phase: "tracking", ...track, finished: false });
    } catch (err) {
      setState({ phase: "error", name: file.name, message: err instanceof Error ? err.message : "The upload failed." });
    }
  }, []);

  const value: Ctx = {
    state,
    pick: () => input.current?.click(),
    reset: () => {
      remember(null);
      setState({ phase: "idle" });
    },
    // Stop is a clean exit: nothing of a stopped upload stays behind. A file not yet loaded is
    // cancelled; a loaded one finishes matching on the server (it cannot be cut in half), then
    // its records are deleted. If this tab closes first, the next upload asks to clear it.
    stop: async () => {
      if (state.phase !== "tracking") return;
      const { jobId, name } = state;
      remember(null);
      const say = (message: string) => setState((s) => (s.phase === "stopped" && s.cleaning ? { ...s, message } : s));
      try {
        const { outcome } = await api.cancelUpload(jobId);
        if (outcome === "cancelled" || outcome === "finished") {
          setState({ phase: "stopped", name, message: stopMessage(outcome) });
          return;
        }
        setState({ phase: "stopped", name, message: stopMessage("running"), cleaning: true });
        await clearUpload(jobId, say, outcome);
        setState({ phase: "stopped", name, message: stopMessage("cleared") });
      } catch (err) {
        const why = err instanceof Error ? err.message : "Could not reach the server.";
        setState({ phase: "stopped", name, message: `${why} Delete it from Your uploads once it finishes.` });
      }
    },
  };

  return (
    <UploadContext.Provider value={value}>
      {children}
      {state.phase === "blocked" && (
        <UploadBlockedDialog
          name={state.name}
          blocking={state.blocking}
          onClear={async (onStatus) => {
            await clearUpload(state.blocking.job_id, onStatus);
            const file = pending.current;
            pending.current = null;
            if (file) void start(file);
            else setState({ phase: "idle" });
          }}
          onCancel={() => {
            pending.current = null;
            setState({ phase: "idle" });
          }}
        />
      )}
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void start(f);
        }}
      />
    </UploadContext.Provider>
  );
}

export function useUpload(): Ctx {
  const ctx = useContext(UploadContext);
  if (!ctx) throw new Error("useUpload outside UploadProvider");
  return ctx;
}
