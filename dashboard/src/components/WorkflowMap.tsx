import type { UploadProgress } from "../api/types";
import type { UploadState } from "../lib/upload";

type Status = "waiting" | "active" | "done" | "failed";

interface Node {
  key: string;
  title: string;
  where: string; // the real component doing the work
  tick: string;
  status: Status;
  lines: string[];
}

const n = (v: number | null | undefined) => (v == null ? "-" : new Intl.NumberFormat("en-IN").format(v));

/** Derive the four stages' state from the live upload (pure: tested via the page). */
export function stages(state: UploadState): Node[] {
  const p: UploadProgress | undefined = state.phase === "tracking" ? state.progress : undefined;
  const job = p?.job;
  const run = p?.match_run;
  const sending = state.phase === "sending";
  const sent = state.phase === "tracking";
  const failedUpload = state.phase === "error";

  const ingest: Status = !sent ? "waiting"
    : job?.status === "COMPLETED" ? "done"
    : job?.status === "FAILED" || job?.status === "EXPIRED" ? "failed" : "active";
  const match: Status = ingest !== "done" ? "waiting"
    : job?.match_status === "DONE" ? "done" : job?.match_status === "FAILED" ? "failed" : "active";
  const emails = Object.values(p?.notifications ?? {}).reduce((a, b) => a + b, 0);
  const notify: Status = match !== "done" ? "waiting" : emails > 0 || !run?.matches_new ? "done" : "active";

  return [
    {
      key: "s3", title: "Upload", where: "Browser → S3 (presigned POST)", tick: "var(--color-acc-2)",
      status: failedUpload ? "failed" : sending ? "active" : sent ? "done" : "waiting",
      lines: failedUpload ? [state.message] : state.phase === "idle" || state.phase === "stopped" ? ["The file goes straight to S3, never through the API"]
        : [`${state.name}`, `${n(Math.round(state.bytes / 1024))} KB`],
    },
    {
      key: "ingest", title: "Validate and load", where: "S3 → SQS → Lambda → RDS", tick: "var(--color-fg)",
      status: ingest,
      lines: job?.total_rows != null
        ? [`${n(job.total_rows)} rows`, `${n(job.inserted)} new, ${n(job.updated)} changed, ${n(job.unchanged)} unchanged`, `${n(job.rejected)} rejected`]
        : job?.error ? [job.error] : ["Every row checked, bad rows kept aside with the reason"],
    },
    {
      key: "match", title: "Workflow B: match", where: "n8n webhook → B → B1 (SQL + AI)", tick: "var(--color-peri)",
      status: match,
      lines: run && match === "done"
        ? [`${n(run.naive_pairs)} pairs → ${n(run.classes)} classes`, `${n(run.llm_calls)} AI calls`, `${n(run.matches_new)} new matches`]
        : ["Users grouped into classes, each class decided once"],
    },
    {
      key: "notify", title: "Workflow C: email", where: "n8n → AWS SES", tick: "var(--color-acc)",
      status: notify,
      lines: notify === "done"
        ? emails ? [`${n(p?.notifications.sent ?? 0)} sent`, `${n(p?.notifications.skipped_demo ?? 0)} held by the demo cap`] : ["No new matches, so no emails"]
        : run?.status === "failed" && notify === "active"
          // n8n died between matching and email: the sweeper proves the run again and finishes it.
          ? ["Interrupted after matching", "The sweeper re-checks and finishes these emails within 10 minutes"]
          : ["Best pick and top picks per user, to test inboxes only"],
    },
  ];
}

const STATUS_LABEL: Record<Status, string> = { waiting: "Waiting", active: "In progress", done: "Done", failed: "Failed" };

export function WorkflowMap({ state }: { state: UploadState }) {
  const nodes = stages(state);
  return (
    <ol className="grid gap-4 lg:grid-cols-4 lg:gap-0 [&>li]:min-w-0" aria-label="Pipeline for this upload">
      {nodes.map((node, i) => (
        <li key={node.key} className="relative lg:pr-6">
          {i < nodes.length - 1 && (
            <span aria-hidden className={`absolute top-1/2 right-0 hidden h-px w-6 lg:block ${node.status === "done" ? "bg-acc" : "bg-line-hi"}`} />
          )}
          <div
            className={`box tick h-full p-6 transition-colors duration-300 ${
              node.status === "active" ? "border-acc" : node.status === "failed" ? "border-coral" : ""
            } ${node.status === "waiting" ? "opacity-70" : ""}`}
            style={{ ["--tick" as string]: node.status === "failed" ? "var(--color-coral)" : node.tick }}
          >
            <div className="flex items-baseline justify-between gap-3">
              <p className="font-semibold tracking-tight">{node.title}</p>
              <p className={`num shrink-0 text-xs ${node.status === "done" ? "text-acc" : node.status === "failed" ? "text-coral" : node.status === "active" ? "text-fg" : "text-mute"}`}>
                {STATUS_LABEL[node.status]}
              </p>
            </div>
            <p className="label mt-1">{node.where}</p>
            <ul className="mt-3 grid gap-0.5 text-sm text-mute">
              {node.lines.map((l) => (
                <li key={l} className="break-words">{l}</li>
              ))}
            </ul>
          </div>
        </li>
      ))}
    </ol>
  );
}
