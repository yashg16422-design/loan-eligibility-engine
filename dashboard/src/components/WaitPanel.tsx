// While an upload runs: what is happening right now, how long it has taken, and what the engine
// is doing behind the scenes. Every fact is a measured number from docs/evidence/.
import { useEffect, useState } from "react";
import type { UploadState } from "../lib/upload";
import { stages } from "./WorkflowMap";

const FACTS = [
  "10,000 customers × 59 products is 590,000 checks. The engine decides 164 classes instead, then expands them back to every customer.",
  "The AI read each lender's criteria once: 5 calls for the first 10,000 customers, and 0 on every run since.",
  "Every run re-checks every customer and lender pair the slow way, before and after writing. Mismatches so far: 0.",
  "In the scale test, one million customers still came down to 360 classes.",
  "Emails only ever reach the project's test inboxes, never the addresses in your file.",
  "The shared free-plan database keeps one upload at a time; deleting it frees its rows and keeps its charts.",
  "A 50 MB file streams straight into PostgreSQL with flat memory: 0.1 MB of Python memory, measured.",
  "ICICI Bank asks self-employed applicants to be 28 or older. The AI turned that sentence into a rule that every class is checked against.",
];

const NOW: Record<string, string> = {
  s3: "Sending your file straight to S3. It never passes through our API, so its size and time limits don't apply.",
  ingest: "The ingest Lambda is streaming your rows into PostgreSQL in one transaction. Bad rows are set aside with the reason.",
  match: "Workflow B is grouping your customers into classes: everyone who gets identical answers from every lender is decided once.",
  notify: "Workflow C is writing each customer's personal email: best pick, top picks and why each one fits.",
};

function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function WaitPanel({ state, onStop }: { state: UploadState; onStop?: () => Promise<void> }) {
  const [now, setNow] = useState(() => Date.now());
  const [asking, setAsking] = useState(false);
  const [stopping, setStopping] = useState(false);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const tracking = state.phase === "tracking" ? state : null;
  const active = stages(state).find((s) => s.status === "active");
  const fact = FACTS[Math.floor(now / 7000) % FACTS.length];
  const since = tracking?.startedAt;

  return (
    <section aria-label="While you wait" className="box tick p-7" style={{ ["--tick" as string]: "var(--color-peri)" }}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="label">While you wait</p>
        {since ? <p className="num text-sm text-mute" aria-label="Time since upload">{clock(now - since)}</p> : null}
      </div>
      <p className="mt-4 text-lg font-light" aria-live="polite">
        {tracking?.reconnecting
          ? "Connection hiccup. The pipeline keeps running on the server; reconnecting…"
          : active?.key === "ingest" && since && now - since > 60_000 && tracking?.progress?.job.status === "AWAITING_UPLOAD"
            // The ingest Lambda could not reach the database yet: SQS retries the file by itself.
            ? "The file is safely in S3, waiting for the database. It is retried automatically within a few minutes; you can also stop it."
            : active
              ? NOW[active.key]
              : "Starting the pipeline…"}
      </p>
      <div aria-hidden className="mt-5 h-px w-full overflow-hidden bg-line">
        <div className="loading-bar h-full w-1/3 bg-peri" />
      </div>
      <p className="mt-5 text-sm text-mute">
        <span className="text-fg">Did you know? </span>
        {fact}
      </p>
      {onStop && tracking && (
        <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-line pt-5 text-sm">
          {asking ? (
            <>
              <span className="text-mute">
                {active?.key === "ingest" || !active
                  ? "Stop this upload? If its file is not loaded yet, nothing will be."
                  : "Stop and clean up? Matching finishes on the server first (it cannot be cut in half), then this upload's records are deleted."}
              </span>
              <button type="button" disabled={stopping} className="btn btn-ghost min-h-9 px-3 text-coral"
                onClick={async () => { setStopping(true); await onStop(); }}>
                {stopping ? "Stopping" : "Yes, stop"}
              </button>
              <button type="button" disabled={stopping} className="btn btn-ghost min-h-9 px-3" onClick={() => setAsking(false)}>Keep going</button>
            </>
          ) : (
            <button type="button" className="btn btn-ghost min-h-9 px-3" onClick={() => setAsking(true)}>Stop</button>
          )}
        </div>
      )}
    </section>
  );
}
