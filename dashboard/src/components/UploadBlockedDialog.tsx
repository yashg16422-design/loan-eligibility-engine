// One upload per account at a time: a new file is refused while the account's last upload is
// still running or still holds customers. Nothing new is uploaded from here.
// - Still loading, matching or emailing: a waiting state (nothing to do; interfering would cut
//   the run or its emails in half). It checks the server every 3 s and moves on by itself.
// - Finished: the person can delete it (charts kept). Then they choose their new file again.
import { CheckCircle, Database } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Blocking } from "../lib/upload";

const n = (v: number) => new Intl.NumberFormat("en-IN").format(v);

const DOING: Record<Blocking["stage"], string> = {
  loading: "loading its customers",
  matching: "matching its customers",
  emailing: "sending its emails",
  stored: "",
};

export function UploadBlockedDialog({
  blocking,
  onDelete,
  onChooseAgain,
  onClose,
}: {
  blocking: Blocking;
  onDelete: (onStatus: (s: string) => void) => Promise<void>;
  onChooseAgain: () => void;
  onClose: () => void;
}) {
  const old = blocking.filename ?? "your last upload";
  const [running, setRunning] = useState(blocking.stage !== "stored");
  const [customers, setCustomers] = useState(blocking.customers);
  const [phase, setPhase] = useState<"ask" | "deleting" | "deleted" | "failed">("ask");
  const [status, setStatus] = useState<string | null>(null);
  const first = useRef<HTMLButtonElement>(null);

  // While it runs, ask the server every 3 s whether it is finished (deletable).
  useEffect(() => {
    if (!running) return;
    let gone = false;
    let timer = 0;
    const check = async () => {
      try {
        const p = await api.upload(blocking.job_id);
        if (gone) return;
        if (p.job.deletable !== false && p.job.status !== "PROCESSING" && p.job.status !== "AWAITING_UPLOAD") {
          setCustomers((p.job.inserted ?? 0) + (p.job.updated ?? 0));
          setRunning(false);
          return;
        }
      } catch {
        /* a blip: ask again */
      }
      if (!gone) timer = window.setTimeout(check, 3000);
    };
    timer = window.setTimeout(check, 3000);
    return () => {
      gone = true;
      window.clearTimeout(timer);
    };
  }, [running, blocking.job_id]);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && phase !== "deleting") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, onClose, running]);

  async function remove() {
    setPhase("deleting");
    try {
      await onDelete(setStatus);
      setPhase("deleted");
      setStatus(null);
    } catch (err) {
      setPhase("failed");
      setStatus(err instanceof Error ? err.message : "Nothing was deleted. Try again.");
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/80 px-4 backdrop-blur-sm">
      <div role="dialog" aria-modal="true" aria-labelledby="blocked-title" className="box tick w-full max-w-[560px] p-7"
        style={{ ["--tick" as string]: "var(--color-acc)" }}>
        <p className="flex items-center gap-2 text-sm text-acc">
          <Database size={18} aria-hidden /> One upload per account
        </p>

        {phase === "deleted" ? (
          <>
            <h2 id="blocked-title" className="mt-4 text-2xl font-light">{old} is deleted</h2>
            <p role="status" className="mt-4 flex items-center gap-2 text-sm text-acc">
              <CheckCircle size={18} aria-hidden /> Its analytics and run history are kept. You can upload your next file now.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <button ref={first} type="button" onClick={onChooseAgain} className="btn btn-primary">Choose CSV</button>
              <button type="button" onClick={onClose} className="btn btn-ghost">Close</button>
            </div>
          </>
        ) : running ? (
          <>
            <h2 id="blocked-title" className="mt-4 text-2xl font-light">{old} is still {DOING[blocking.stage] || "running"}</h2>
            <p className="mt-4 text-sm text-mute">
              Each account keeps one upload at a time on the shared free-plan database. Your new file can be uploaded once
              this one has finished and you have deleted it.
            </p>
            <p role="status" aria-live="polite" className="mt-5 flex items-start gap-3 text-sm text-fg">
              <span className="mail-dots mt-2 inline-flex shrink-0 items-center gap-1 text-acc" aria-hidden>
                <span /><span /><span />
              </span>
              Working on it on the server. This updates by itself when it is done.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <button ref={first} type="button" onClick={onClose} className="btn btn-ghost">OK, I will wait</button>
            </div>
          </>
        ) : (
          <>
            <h2 id="blocked-title" className="mt-4 text-2xl font-light">You already have {old}</h2>
            <p className="mt-4 text-sm text-mute">
              It still has {n(customers)} customers stored. Each account keeps one upload at a time on the shared
              free-plan database (Amazon RDS db.t4g.micro, 1 GB), so delete it before uploading another file. Its
              analytics and run history are kept.
            </p>
            {status && (
              <p role="status" className={`mt-4 text-sm ${phase === "failed" ? "text-coral" : "text-fg"}`}>{status}</p>
            )}
            <div className="mt-6 flex flex-wrap gap-3">
              <button ref={first} type="button" disabled={phase === "deleting"} onClick={remove} className="btn btn-primary">
                {phase === "deleting" ? "Deleting" : phase === "failed" ? "Try again" : `Delete ${old}`}
              </button>
              <button type="button" disabled={phase === "deleting"} onClick={onClose} className="btn btn-ghost">Cancel</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
