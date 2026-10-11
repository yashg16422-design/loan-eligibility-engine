// Bulk CSV upload, available from every page (the header button). One upload at a time;
// progress comes from GET /uploads/{job_id} (the same endpoint the original upload page uses).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { UploadProgress } from "../api/types";
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
  | { phase: "stopped"; name: string; message: string };

interface Ctx {
  state: UploadState;
  pick: () => void;
  reset: () => void;
  stop: () => Promise<void>;
}

/** What Stop did, in words (server outcome -> sentence). */
export function stopMessage(outcome: string): string {
  if (outcome === "cancelled") return "Stopped. The file was never loaded, so nothing was matched or emailed.";
  if (outcome === "running")
    return "Stopped watching. The customers were already loaded and matching runs on the server until it finishes; delete the upload afterwards to remove its data.";
  return "This upload had already finished. Delete it below if you want its customers removed.";
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
      const ticket = await api.createUpload(file.name);
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
    stop: async () => {
      if (state.phase !== "tracking") return;
      const { jobId, name } = state;
      remember(null);
      try {
        const { outcome } = await api.cancelUpload(jobId);
        setState({ phase: "stopped", name, message: stopMessage(outcome) });
      } catch (err) {
        setState({ phase: "stopped", name, message: err instanceof Error ? err.message : "Could not reach the server. Stopped watching." });
      }
    },
  };

  return (
    <UploadContext.Provider value={value}>
      {children}
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
