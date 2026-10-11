// After a finished upload: ask to delete its customer records so the shared demo database stays
// small. The analytics stay on the page (a snapshot is kept server-side before the delete).
import { Database } from "@phosphor-icons/react";
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
  const first = useRef<HTMLButtonElement>(null);

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
          <Database size={18} aria-hidden /> Run complete: matched, double-checked, emails sent
        </p>
        <h2 id="freeup-title" className="mt-4 text-2xl font-light">Free up the shared database?</h2>
        <p className="mt-4 text-sm text-mute">
          This demo runs on AWS's free plan: one small database (Amazon RDS db.t4g.micro, 1 GB of memory) shared by every
          reviewer. Each 10,000-customer upload adds about 260,000 match rows, and with more than about three live at once
          the database starts swapping and every upload slows down.
        </p>
        <p className="mt-3 text-sm text-mute">
          Deleting removes this upload's {n(customers)} customer records, their matches and email records.{" "}
          <span className="text-fg">Your analytics stay on this page</span>, and the run history and Treasure Hunt numbers
          are kept. The database keeps one upload at a time, so other reviewers can upload only after this is deleted.
        </p>
        {status && (
          <p role="status" className={`mt-4 text-sm ${failed ? "text-coral" : "text-fg"}`}>{status}</p>
        )}
        <div className="mt-6 flex flex-wrap gap-3">
          <button ref={first} type="button" disabled={busy} onClick={remove} className="btn btn-primary">
            {busy ? "Deleting" : "Delete records, keep analytics"}
          </button>
          <button type="button" disabled={busy} onClick={onClose} className="btn btn-ghost">Keep for now</button>
        </div>
      </div>
    </div>
  );
}
