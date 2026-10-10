import { FileCsv, SealCheck, UploadSimple, WarningCircle, XCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type DragEvent } from "react";
import { api } from "../api/client";
import type { Analytics, CrawlHealth, Run, UploadRecord, WorkflowError } from "../api/types";
import { AnalyticsGrid } from "../components/AnalyticsGrid";
import { WorkflowMap } from "../components/WorkflowMap";
import { CHANNEL_LABEL } from "../lib/offers";
import { useUpload } from "../lib/upload";
import { uploadKeys } from "../lib/uploadKeys";
import { Link } from "../router";
import { useIsAdmin } from "../lib/useAccount";
import { HBars } from "../ui/charts";
import { ConfirmDelete } from "../ui/Confirm";

const n = (v: number | null | undefined) => (v == null ? "-" : new Intl.NumberFormat("en-IN").format(v));

function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** The biggest recent upload run: the reference picture when nothing is running. */
function featured(runs: Run[]): Run | undefined {
  const reference = runs.find((r) => r.reference); // the API always includes the full-file run
  if (reference) return reference;
  return runs
    .filter((r) => r.status === "done" && r.mode === "upload" && r.job_id)
    .reduce<Run | undefined>((best, r) => ((r.users_in ?? 0) > (best?.users_in ?? 0) ? r : best), undefined);
}

export function Overview() {
  const upload = useUpload();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [crawl, setCrawl] = useState<CrawlHealth | null>(null);
  const [errors, setErrors] = useState<WorkflowError[] | null>(null);
  const [analytics, setAnalytics] = useState<{ jobId: string; data: Analytics } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadRecord[] | null>(null);
  const [selected, setSelected] = useState<UploadRecord | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [r, c, e, u] = await Promise.all([api.runs(), api.crawl(), api.errors(), api.uploads()]);
      setRuns(r);
      setCrawl(c);
      setErrors(e);
      setUploads(u);
      setFailed(null);
    } catch (err) {
      setFailed(err instanceof Error ? err.message : "The engine status could not be loaded.");
    }
  }, []);
  useEffect(() => void refresh(), [refresh]);

  const live = upload.state.phase === "tracking" ? upload.state : null;
  // The workflow numbers come from run history (kept even after a data reset); the charts need
  // an upload whose users are still in the database.
  const reference = runs ? featured(runs) : undefined;
  // Default charts: the upload with the most users still in the database (from the uploads list,
  // so test runs or a data reset can never push the reference upload out of view).
  const biggest = uploads
    ?.filter((u) => !u.purged_at && u.users_now > 0)
    .reduce<UploadRecord | undefined>((b, u) => (u.users_now > (b?.users_now ?? 0) ? u : b), undefined);
  // Charts: the upload picked in the table, else the live upload once loaded, else the biggest.
  const chartJob = selected?.job_id ?? (live?.finished ? live.jobId : biggest?.job_id ?? null);

  useEffect(() => {
    if (!chartJob) return;
    let gone = false;
    api.analytics(chartJob).then((data) => !gone && setAnalytics({ jobId: chartJob, data })).catch(() => {});
    return () => {
      gone = true;
    };
  }, [chartJob]);
  useEffect(() => {
    if (live?.finished) void refresh(); // the new run joins the history
  }, [live?.finished, refresh]);
  useEffect(() => {
    if (live?.jobId) {
      setSelected(null); // a new upload takes over the charts
      void api.uploads().then(setUploads).catch(() => {});
    }
  }, [live?.jobId]);

  const p = live?.progress;
  const run = p?.match_run;

  return (
    <div className="mx-auto max-w-[1480px] px-5 pt-14 pb-10 lg:pt-20 sm:px-10 xl:px-16">
      <h1 className="text-3xl sm:text-4xl">Upload users. Watch every lender get checked.</h1>
      <p className="mt-5 max-w-[68ch] text-lg text-mute">
        A CSV goes straight to S3, is validated into the database, matched against every crawled loan product by
        Workflow B, and each matched user is emailed by Workflow C. Every number below is read from the live database.
      </p>
      {failed && (
        <p role="alert" className="mt-4 flex items-center gap-2 text-sm text-coral">
          <WarningCircle size={16} aria-hidden /> {failed}
          <button type="button" className="underline" onClick={refresh}>Try again</button>
        </p>
      )}

      {/* 1. Bulk upload + the pipeline it runs (the assignment's core path). */}
      <section aria-labelledby="upload-title" className="mt-14 grid gap-8">
        <DropZone />
        <WorkflowMap state={upload.state} />
        {p && (
          <div className="grid gap-px border border-line bg-line lg:grid-cols-2" aria-live="polite">
            <section className="bg-panel p-7">
              <h3 className="text-base font-semibold">Rows in this file</h3>
              <div className="mt-5">
                {p.job.total_rows == null ? (
                  <p className="text-sm text-mute">Waiting for the file to be validated.</p>
                ) : (
                  <HBars rows={[
                    { label: "New users", value: p.job.inserted ?? 0 },
                    { label: "Changed users", value: p.job.updated ?? 0, color: "var(--color-acc-2)" },
                    { label: "Unchanged (already up to date)", value: p.job.unchanged ?? 0, color: "var(--color-dim)" },
                    { label: "Rejected (see reasons below)", value: p.job.rejected ?? 0, color: "var(--color-coral)" },
                  ]} />
                )}
                {p.rejects.length > 0 && (
                  <ul className="mt-5 grid gap-1 text-sm text-mute">
                    {p.rejects.slice(0, 4).map((r) => (
                      <li key={r.row_number}><span className="num text-coral">line {r.row_number}</span> {r.reason.replace(/_/g, " ")}</li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
            <section className="bg-panel p-7">
              <h3 className="text-base font-semibold">How Workflow B narrowed the work</h3>
              <div className="mt-5">
                {run && p.job.match_status === "DONE" ? (
                  <HBars log rows={[
                    { label: "User and product pairs", value: run.naive_pairs ?? 0, color: "var(--color-coral)" },
                    { label: "Pairs passing published rules", value: run.pairs_after_sql ?? 0, color: "var(--color-amber)" },
                    { label: "Classes (users who get identical answers)", value: run.classes ?? 0, color: "var(--color-peri)" },
                    { label: "AI calls", value: run.llm_calls ?? 0, color: "var(--color-peri)" },
                    { label: "New matches", value: run.matches_new ?? 0 },
                  ]} />
                ) : (
                  <p className="text-sm text-mute">Appears when matching finishes, usually a few seconds after loading.</p>
                )}
              </div>
            </section>
          </div>
        )}
      </section>

      {/* 2. Every upload is its own record: view its charts, or delete its users to start again. */}
      <UploadsTable
        uploads={uploads}
        selected={chartJob}
        onView={(u) => setSelected(u)}
        onDeleted={async (jobId) => {
          if (selected?.job_id === jobId) setSelected(null);
          if (live?.jobId === jobId) upload.reset();
          setAnalytics(null);
          await refresh();
        }}
      />

      {/* 3. What the users in that file look like and what they matched. */}
      <section aria-labelledby="analytics-title" className="mt-24">
        <h2 id="analytics-title" className="text-2xl">
          {selected
            ? `Upload: ${selected.original_filename ?? "users.csv"}`
            : live?.finished
              ? `Your upload: ${live.name}`
              : biggest
                ? `Largest upload: ${biggest.original_filename ?? "users.csv"}, ${n(biggest.users_now)} users`
                : "Upload analytics"}
        </h2>
        <p className="mt-3 text-mute">
          {selected
            ? `${n(selected.users_now)} users this file added or changed, uploaded ${ago(selected.created_at)}.`
            : live?.finished
            ? "Profiles and matches of the users this file added or changed."
            : biggest
              ? `Uploaded ${ago(biggest.created_at)}. Pick any upload in the table, or upload a file, to see its own charts.`
              : uploads
                ? "No uploaded users in the database yet. Upload a CSV and its charts form here as it runs."
                : "Loading"}
        </p>
        <div className="mt-10">
          {chartJob && analytics?.jobId === chartJob ? (
            <AnalyticsGrid data={analytics.data} />
          ) : chartJob || !uploads ? (
            <div className="h-72 border border-line bg-panel" aria-busy="true" />
          ) : null}
        </div>
      </section>

      {/* 4. The workflows the assignment asks for, with their triggers and real numbers. */}
      <section aria-labelledby="workflows-title" className="mt-24">
        <h2 id="workflows-title" className="text-2xl">The workflows</h2>
        <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
          <WorkflowCard tick="var(--color-amber)" name="A · Loan discovery" trigger="Every day at 06:00 IST, and on demand">
            {crawl ? (
              <>
                <Stat label="Products" value={n(crawl.products.reduce((s, p) => s + p.products, 0))} />
                <Stat label="Criteria verified on the page" value={n(crawl.products.reduce((s, p) => s + p.verified, 0))} />
                <p className="mt-3 text-sm text-mute">
                  {crawl.products.map((p) => `${CHANNEL_LABEL[p.channel]} ${p.products}`).join(", ")}.
                  {crawl.latest_run && ` Last crawl ${ago(crawl.latest_run.started_at)}.`}
                </p>
              </>
            ) : <Skeleton />}
          </WorkflowCard>
          <WorkflowCard tick="var(--color-peri)" name="B · Matching" trigger="After every upload (webhook), a 10-minute sweeper, and when A changes a product">
            {reference ? (
              <>
                <Stat label="Pairs to check" value={n(reference.naive_pairs)} />
                <Stat label="Decided as classes" value={n(reference.classes)} />
                <Stat label="AI calls" value={n(reference.llm_calls)} />
                {reference.correctness_ok && (
                  <p className="mt-3 flex items-center gap-1.5 text-sm text-acc">
                    <SealCheck size={16} weight="fill" aria-hidden /> Same result as checking every pair
                  </p>
                )}
              </>
            ) : <Skeleton />}
          </WorkflowCard>
          <WorkflowCard tick="var(--color-acc)" name="C · Notification" trigger="Right after each matching run">
            {runs ? (
              <>
                <Stat label="Emails sent (recent runs)" value={n(runs.reduce((s, r) => s + (r.emails_sent ?? 0), 0))} />
                <Stat label="Held by the demo cap" value={n(runs.reduce((s, r) => s + (r.emails_skipped_demo ?? 0), 0))} />
                <p className="mt-3 text-sm text-mute">Personalised best pick and top picks via AWS SES, to test inboxes only.</p>
              </>
            ) : <Skeleton />}
          </WorkflowCard>
          <WorkflowCard tick="var(--color-coral)" name="E · Error handler" trigger="Whenever A, B or C fails">
            {errors ? (
              <>
                <Stat label="Failures recorded" value={n(errors.length)} />
                <p className="mt-3 text-sm text-mute">
                  {errors[0] ? `Latest: ${errors[0].workflow}, ${ago(errors[0].created_at)}.` : "No failures recorded."} Each burst emails the operator once.
                </p>
              </>
            ) : <Skeleton />}
          </WorkflowCard>
        </div>
      </section>

      {/* 4. History. */}
      <section aria-labelledby="runs-title" className="mt-24">
        <h2 id="runs-title" className="text-2xl">Recent matching runs</h2>
        <div className="mt-10 overflow-x-auto border border-line">
          <table className="w-full min-w-[860px] border-collapse text-sm">
            <thead className="bg-panel text-left">
              <tr className="[&_th]:px-5 [&_th]:py-4 [&_th]:font-normal [&_th]:text-mute">
                <th>When</th><th>Trigger</th><th className="text-right">Users</th><th className="text-right">Pairs</th>
                <th className="text-right">Classes</th><th className="text-right">AI calls</th><th className="text-right">New matches</th>
                <th className="text-right">Emails</th><th className="text-right">Time</th><th>Check</th>
              </tr>
            </thead>
            <tbody>
              {(runs ?? []).map((r) => (
                <tr key={r.run_id} className="border-t border-line [&_td]:px-5 [&_td]:py-3.5">
                  <td>{ago(r.started_at)}</td>
                  <td className="text-mute">
                    {r.mode === "upload" ? "Upload or check" : "Product change"}
                    {r.reference && <span className="label ml-2">full-file reference</span>}
                    {r.purged && <span className="label ml-2">data deleted</span>}
                  </td>
                  <td className="num text-right">{n(r.users_in)}</td>
                  <td className="num text-right">{n(r.naive_pairs)}</td>
                  <td className="num text-right">{n(r.classes)}</td>
                  <td className="num text-right">{n(r.llm_calls)}</td>
                  <td className="num text-right">{n(r.matches_new)}</td>
                  <td className="num text-right">{n(r.emails_sent)}</td>
                  <td className="num text-right">{r.seconds != null ? `${r.seconds} s` : "-"}</td>
                  <td>
                    {r.status === "failed" ? <XCircle size={18} className="text-coral" aria-label="failed" />
                      : r.correctness_ok ? <SealCheck size={18} weight="fill" className="text-acc" aria-label="identical to checking every pair" />
                      : <span className="text-mute">-</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-mute">
          Checking one person instead? <Link to="check" className="underline">Check eligibility</Link> runs them through this same pipeline.
        </p>
      </section>
    </div>
  );
}

function DropZone() {
  const { state, pick, reset } = useUpload();
  const [over, setOver] = useState(false);
  const busy = state.phase === "sending" || (state.phase === "tracking" && !state.finished);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (!f || busy) return;
    const dt = new DataTransfer();
    dt.items.add(f);
    const input = document.querySelector<HTMLInputElement>('input[type="file"][accept=".csv,text/csv"]');
    if (input) {
      input.files = dt.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };
  return (
    <div
      onDragOver={(e) => (e.preventDefault(), setOver(true))}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={`box tick flex flex-wrap items-center justify-between gap-6 p-8 ${over ? "border-acc" : ""}`}
    >
      <div className="flex items-start gap-4">
        <FileCsv size={32} className="mt-0.5 shrink-0 text-acc" aria-hidden />
        <div>
          <h2 id="upload-title" className="text-xl">Bulk upload a users CSV</h2>
          <p className="mt-1 max-w-[62ch] text-sm text-mute">
            Columns: user_id, name, email, monthly_income, credit_score, employment_status, age. Up to 50 MB. Drop it
            here or choose a file. Emails only ever go to the project's test inboxes.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {(state.phase === "error" || (state.phase === "tracking" && state.finished)) && (
          <button type="button" onClick={reset} className="btn btn-ghost">Clear</button>
        )}
        <button type="button" onClick={pick} disabled={busy} className="btn btn-primary">
          <UploadSimple size={16} aria-hidden /> {busy ? "Running" : "Choose CSV"}
        </button>
      </div>
    </div>
  );
}

function uploadState(u: UploadRecord): { text: string; tone: string } {
  if (u.purged_at) return { text: "Data deleted", tone: "text-mute" };
  if (u.status === "FAILED") return { text: "Failed", tone: "text-coral" };
  if (u.status === "AWAITING_UPLOAD") return { text: "Waiting for file", tone: "text-mute" };
  if (u.status === "PROCESSING") return { text: "Loading", tone: "text-amber" };
  if (u.match_status === "FAILED") return { text: "Matching failed", tone: "text-coral" };
  if (u.match_status !== "DONE") return { text: "Matching", tone: "text-peri" };
  return { text: "Done", tone: "text-acc" };
}

/**
 * Every bulk upload as its own record. View shows its charts below; Delete removes the users it
 * added or changed (with their matches and email records), so the same file can be uploaded
 * again and run as new. Allowed for the browser that uploaded it, and for admins.
 */
function UploadsTable({
  uploads,
  selected,
  onView,
  onDeleted,
}: {
  uploads: UploadRecord[] | null;
  selected: string | null;
  onView: (u: UploadRecord) => void;
  onDeleted: (jobId: string) => Promise<void>;
}) {
  const admin = useIsAdmin();
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const report = async (work: () => Promise<string>, jobId: string) => {
    try {
      setResult({ ok: true, text: await work() });
      await onDeleted(jobId);
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : "Nothing was deleted. Try again." });
    }
  };
  const remove = (u: UploadRecord) =>
    report(async () => {
      const key = uploadKeys.get(u.job_id);
      const r = key ? await api.deleteMyUpload(u.job_id, key) : await api.purgeUpload(u.job_id);
      return `Deleted ${n(r.deleted_users)} users from ${u.original_filename ?? "that upload"}. Upload it again to run it as new.`;
    }, u.job_id);

  return (
    <section aria-labelledby="uploads-title" className="mt-24">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 id="uploads-title" className="text-2xl">Uploads</h2>
          <p className="mt-3 max-w-[72ch] text-mute">
            Each CSV is its own record. Deleting one removes the users it added or changed, with their matches and emails, so
            the file can be uploaded again and run as new. Products, run history and accounts stay.
          </p>
        </div>
        {admin && (
          <ConfirmDelete
            small
            label="Delete all uploaded users"
            question="Delete every user that came from a CSV?"
            onConfirm={() =>
              report(async () => {
                const r = await api.purgeAllUploads();
                return `Deleted ${n(r.deleted_users)} users from ${n(r.uploads)} uploads.`;
              }, "")
            }
          />
        )}
      </div>
      {result && <p role="status" className={`mt-4 text-sm ${result.ok ? "text-acc" : "text-coral"}`}>{result.text}</p>}
      <div className="mt-8 overflow-x-auto border border-line">
        <table className="w-full min-w-[980px] border-collapse text-sm">
          <thead className="bg-panel text-left">
            <tr className="[&_th]:px-5 [&_th]:py-4 [&_th]:font-normal [&_th]:text-mute">
              <th>File</th><th className="text-right">Rows</th><th className="text-right">New</th><th className="text-right">Changed</th>
              <th className="text-right">Rejected</th><th className="text-right">Users now</th><th className="text-right">Matches</th>
              <th className="text-right">Emails</th><th>Status</th><th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {uploads === null ? (
              <tr><td colSpan={10} className="h-24 bg-panel" aria-busy="true" /></tr>
            ) : uploads.length === 0 ? (
              <tr><td colSpan={10} className="px-5 py-8 text-mute">No uploads yet. Choose a CSV above and it appears here as it runs.</td></tr>
            ) : (
              uploads.map((u) => {
                const state = uploadState(u);
                const canDelete = !u.purged_at && u.users_now > 0 && (admin || uploadKeys.get(u.job_id) !== undefined);
                return (
                  <tr key={u.job_id} className={`border-t border-line align-middle [&_td]:px-5 [&_td]:py-3.5 ${selected === u.job_id ? "bg-panel-2" : ""}`}>
                    <td>
                      <span className="block max-w-[260px] truncate font-medium">{u.original_filename ?? "users.csv"}</span>
                      <span className="label">{ago(u.created_at)}</span>
                    </td>
                    <td className="num text-right">{n(u.total_rows)}</td>
                    <td className="num text-right">{n(u.inserted)}</td>
                    <td className="num text-right">{n(u.updated)}</td>
                    <td className={`num text-right ${u.rejected ? "text-coral" : ""}`}>{n(u.rejected)}</td>
                    <td className="num text-right">{n(u.users_now)}</td>
                    <td className="num text-right">{n(u.matches)}</td>
                    <td className="num text-right">{n(u.emails_sent)}</td>
                    <td className={state.tone}>{state.text}</td>
                    <td>
                      <span className="flex items-center justify-end gap-3">
                        {u.users_now > 0 && (
                          <button type="button" onClick={() => onView(u)} aria-pressed={selected === u.job_id}
                            className={`btn btn-ghost min-h-9 px-3 text-sm ${selected === u.job_id ? "border-acc text-acc" : ""}`}>
                            View
                          </button>
                        )}
                        {canDelete && (
                          <ConfirmDelete small label="Delete" question={`Delete ${n(u.users_now)} users?`} onConfirm={() => remove(u)} />
                        )}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function WorkflowCard({ tick, name, trigger, children }: { tick: string; name: string; trigger: string; children: React.ReactNode }) {
  return (
    <article className="box tick p-7" style={{ ["--tick" as string]: tick }}>
      <h3 className="text-lg">{name}</h3>
      <p className="mt-1 text-sm text-mute">{trigger}</p>
      <div className="mt-6 border-t border-line pt-5">{children}</div>
    </article>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <p className="flex items-baseline justify-between gap-3 py-2 text-sm">
      <span className="text-mute">{label}{hint && <span className="label"> ({hint})</span>}</span>
      <span className="num text-lg text-fg">{value}</span>
    </p>
  );
}

function Skeleton() {
  return <div className="h-24 bg-panel-2" aria-busy="true" />;
}
