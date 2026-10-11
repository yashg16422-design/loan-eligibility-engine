// After a finished upload: ask to delete its customer records so the shared demo database stays
// small. The analytics stay on the page (a snapshot is kept server-side before the delete).
// Delete unlocks only once the server says nothing is emailing the upload any more: C1 writes
// every customer's email after the run, and deleting under it would cut that step in half.
import { CheckCircle, Database } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

const n = (v: number) => new Intl.NumberFormat("en-IN").format(v);

export function FreeUpDialog({
  jobId,
  customers,
  onClose,
  onDeleted,
}: {
  jobId: string;
  customers: number;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState<boolean | null>(null); // null: still checking
  const first = useRef<HTMLButtonElement>(null);

  // Ask the server every 3 s until the upload is deletable (emails all written).
  useEffect(() => {
    let gone = false;
    let timer = 0;
    const check = async () => {
      try {
        const p = await api.upload(jobId);
        if (gone) return;
        const ok = p.job.deletable !== false;
        setReady(ok);
        if (!ok) timer = window.setTimeout(check, 3000);
      } catch {
        if (!gone) timer = window.setTimeout(check, 5000); // a blip: ask again
      }
    };
    void check();
    return () => {
      gone = true;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function remove() {
    setBusy(true);
    setFailed(false);
    try {
      await api.purgeUpload(jobId, (deleted, left, waiting) =>
        setStatus(waiting ? "Waiting for its emails to finish…" : left > 0 ? `Deleting… ${n(deleted)} done, ${n(left)} to go.` : "Deleted."),
      );
      onDeleted();
    } catch (err) {
      setFailed(true);
      setStatus(err instanceof Error ? err.message : "Nothing was deleted. Try again from Your uploads.");
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/80 px-4 backdrop-blur-sm">
      <div role="dialog" aria-modal="true" aria-labelledby="freeup-title" className="box tick w-full max-w-[560px] p-7"
        style={{ ["--tick" as string]: "var(--color-acc)" }}>
        <p className="flex items-center gap-2 text-sm text-acc">
          <Database size={18} aria-hidden />{" "}
          {ready === true ? "Run complete: matched, double-checked, emails sent" : "Matched and double-checked; emails still being written"}
        </p>
        <h2 id="freeup-title" className="mt-4 text-2xl font-light">Free up the shared database?</h2>
        <p className="mt-4 text-sm text-mute">
          This demo runs on AWS's free plan: one small database (Amazon RDS db.t4g.micro, 1 GB of memory) shared by every
          reviewer. Each 10,000-customer upload adds about 260,000 match rows; with two stored and a delete running, it once
          ran out of memory and AWS restarted it.
        </p>
        <p className="mt-3 text-sm text-mute">
          Deleting removes this upload's {n(customers)} customer records, their matches and email records.{" "}
          <span className="text-fg">Your analytics stay on this page</span>, and the run history and Treasure Hunt numbers
          are kept. Each account keeps one upload at a time, so it is deleted before your next upload anyway.
        </p>
        {status ? (
          <p role="status" className={`mt-4 text-sm ${failed ? "text-coral" : "text-fg"}`}>{status}</p>
        ) : ready === true ? (
          <p role="status" className="mt-5 flex items-center gap-2 text-sm text-acc">
            <CheckCircle size={18} aria-hidden /> Emails finished. It is safe to delete now.
          </p>
        ) : (
          <p role="status" aria-live="polite" className="mt-5 flex items-start gap-3 text-sm text-fg">
            <span className="mail-dots mt-2 inline-flex shrink-0 items-center gap-1 text-acc" aria-hidden>
              <span /><span /><span />
            </span>
            {ready === null
              ? "Checking the emails…"
              : "Finishing the emails: Workflow C1 is writing every customer's email. Delete unlocks as soon as it is done."}
          </p>
        )}
        <div className="mt-6 flex flex-wrap gap-3">
          <button ref={first} type="button" disabled={busy || ready !== true} onClick={remove} className="btn btn-primary">
            {busy ? "Deleting" : ready !== true ? "Waiting for emails" : "Delete records, keep analytics"}
          </button>
          <button type="button" disabled={busy} onClick={onClose} className="btn btn-ghost">Keep for now</button>
        </div>
      </div>
    </div>
  );
}
