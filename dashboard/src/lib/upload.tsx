// Bulk CSV upload, available from every page (the header button). One upload at a time;
// progress comes from GET /uploads/{job_id} (the same endpoint the original upload page uses).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { UploadProgress } from "../api/types";
import { navigate } from "../router";
import { uploadKeys } from "./uploadKeys";

export type UploadState =
  | { phase: "idle" }
  | { phase: "sending"; name: string; bytes: number }
  | { phase: "tracking"; name: string; bytes: number; jobId: string; progress?: UploadProgress; finished: boolean }
  | { phase: "error"; name?: string; message: string };

interface Ctx {
  state: UploadState;
  pick: () => void;
  reset: () => void;
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

export function UploadProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (state.phase !== "tracking" || state.finished) return;
    const id = window.setTimeout(async () => {
      try {
        const progress = await api.upload(state.jobId);
        setState((s) => (s.phase === "tracking" ? { ...s, progress, finished: isFinished(progress) } : s));
      } catch {
        setState((s) => ({ ...s })); // transient: poll again
      }
    }, 1500);
    return () => window.clearTimeout(id);
  }, [state]);

  const start = useCallback(async (file: File) => {
    navigate("overview");
    setState({ phase: "sending", name: file.name, bytes: file.size });
    try {
      if (!/\.csv$/i.test(file.name)) throw new ApiError(400, "Choose a .csv file.");
      const ticket = await api.createUpload(file.name);
      uploadKeys.set(ticket.job_id, ticket.delete_key); // lets this browser delete it later
      if (file.size > ticket.max_bytes) throw new ApiError(413, "That file is larger than 50 MB.");
      const form = new FormData();
      Object.entries(ticket.upload.fields).forEach(([k, v]) => form.append(k, v));
      form.append("file", new Blob([file], { type: "text/csv" }), file.name);
      const res = await fetch(ticket.upload.url, { method: "POST", body: form });
      if (!res.ok) throw new ApiError(res.status, "Storage refused the file. Check it is a CSV under 50 MB.");
      setState({ phase: "tracking", name: file.name, bytes: file.size, jobId: ticket.job_id, finished: false });
    } catch (err) {
      setState({ phase: "error", name: file.name, message: err instanceof Error ? err.message : "The upload failed." });
    }
  }, []);

  const value: Ctx = {
    state,
    pick: () => input.current?.click(),
    reset: () => setState({ phase: "idle" }),
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
