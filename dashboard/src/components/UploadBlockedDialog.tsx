// A new upload while the account's last one is still running or still holds customers: one
// upload at a time keeps the shared free-plan database small. Offers to clear the old one
// (stop, let it finish, delete), then uploads the new file by itself.
import { Database } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import type { Blocking } from "../lib/upload";

const n = (v: number) => new Intl.NumberFormat("en-IN").format(v);

export function UploadBlockedDialog({
  name,
  blocking,
  onClear,
  onCancel,
}: {
  name: string;
  blocking: Blocking;
  onClear: (onStatus: (s: string) => void) => Promise<void>;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const first = useRef<HTMLButtonElement>(null);
  const old = blocking.filename ?? "Your last upload";
  const running = blocking.stage !== "stored";

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  async function clear() {
    setBusy(true);
    setFailed(false);
    try {
      await onClear(setStatus);
    } catch (err) {
      setFailed(true);
      setStatus(err instanceof Error ? err.message : "That did not work. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/80 px-4 backdrop-blur-sm">
      <div role="dialog" aria-modal="true" aria-labelledby="blocked-title" className="box tick w-full max-w-[560px] p-7"
        style={{ ["--tick" as string]: "var(--color-acc)" }}>
        <p className="flex items-center gap-2 text-sm text-acc">
          <Database size={18} aria-hidden /> One upload at a time
        </p>
        <h2 id="blocked-title" className="mt-4 text-2xl font-light">
          {running ? `${old} is still ${blocking.stage}` : `Delete ${old} first?`}
        </h2>
        <p className="mt-4 text-sm text-mute">
          {running
            ? "Stopping clears it completely: a file not yet loaded is cancelled; one already matching finishes on the server first (usually within two minutes), then its records are deleted."
            : `It still has ${n(blocking.customers)} customers stored. This demo shares one small free-plan database (Amazon RDS db.t4g.micro, 1 GB) between every reviewer, so it keeps one upload at a time.`}
        </p>
        <p className="mt-3 text-sm text-mute">
          {running ? "" : "Its analytics and run history are kept. "}
          Then <span className="text-fg">{name}</span> uploads by itself.
        </p>
        {status && (
          <p role="status" className={`mt-4 text-sm ${failed ? "text-coral" : "text-fg"}`}>{status}</p>
        )}
        <div className="mt-6 flex flex-wrap gap-3">
          <button ref={first} type="button" disabled={busy} onClick={clear} className="btn btn-primary">
            {busy ? "Clearing" : failed ? "Try again" : running ? "Stop it, then upload" : "Delete it, then upload"}
          </button>
          <button type="button" disabled={busy} onClick={onCancel} className="btn btn-ghost">
            {running ? "Keep it running" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
