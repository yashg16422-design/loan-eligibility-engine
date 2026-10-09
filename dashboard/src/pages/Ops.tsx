import { CheckCircle, CircleNotch, FileCsv, SealCheck, UploadSimple, WarningCircle, XCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { api, ApiError } from "../api/client";
import type { CrawlHealth, Run, UploadProgress, WorkflowError } from "../api/types";
import { Pipeline } from "../components/Pipeline";
import { CHANNEL_LABEL } from "../lib/offers";

const n = (v: number | null | undefined) => (v == null ? "-" : new Intl.NumberFormat("en-IN").format(v));

function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** The run worth showing first: the biggest recent one (a 1-user check is a dull funnel). */
function featured(runs: Run[]): Run | undefined {
  const done = runs.filter((r) => r.status === "done");
  return done.reduce<Run | undefined>((best, r) => ((r.naive_pairs ?? 0) > (best?.naive_pairs ?? -1) ? r : best), undefined);
}

export function Ops() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [crawl, setCrawl] = useState<CrawlHealth | null>(null);
  const [errors, setErrors] = useState<WorkflowError[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [r, c, e] = await Promise.all([api.runs(), api.crawl(), api.errors()]);
      setRuns(r);
      setCrawl(c);
      setErrors(e);
      setFailed(null);
    } catch (err) {
      setFailed(err instanceof Error ? err.message : "The engine status could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = runs?.find((r) => r.run_id === selected) ?? (runs ? featured(runs) : undefined);

  return (
    <div className="mx-auto max-w-[1240px] px-4 pt-10 pb-16 sm:px-6">
      <h1 className="text-2xl font-semibold sm:text-3xl">The engine, live</h1>
      <p className="mt-2 max-w-[62ch] text-muted">
        Every matching run, how it narrowed the work, and the health of the lender crawl. Numbers come straight from the
        database; nothing on this page is illustrative.
      </p>
      {failed && (
        <p role="alert" className="mt-6 flex items-center gap-2 text-sm text-danger">
          <WarningCircle size={16} aria-hidden /> {failed}
          <button type="button" onClick={refresh} className="underline">Try again</button>
        </p>
      )}

      <section aria-labelledby="pipeline-title" className="mt-12">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <h2 id="pipeline-title" className="text-lg font-medium">
            {run ? `${run.mode === "upload" ? "Upload" : "Product change"} run, ${ago(run.started_at)}` : "Matching run"}
          </h2>
          {run && <p className="text-sm text-muted">{run.mode === "products" ? "Triggered by the daily crawl" : "Triggered by a CSV upload or a check"}</p>}
        </div>
        <div className="mt-8">{run ? <Pipeline run={run} /> : <div className="h-40 animate-pulse rounded bg-panel" />}</div>
      </section>

      <section aria-labelledby="runs-title" className="mt-16">
        <h2 id="runs-title" className="text-lg font-medium">Recent runs</h2>
        <p className="mt-1 text-sm text-muted">Select a run to replay its pipeline above.</p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="[&_th]:pb-2 [&_th]:font-normal">
                <th>When</th><th>Trigger</th><th className="text-right">Users</th><th className="text-right">Pairs</th>
                <th className="text-right">Classes</th><th className="text-right">AI calls</th><th className="text-right">New matches</th>
                <th className="text-right">Emails</th><th className="text-right">Time</th><th className="pl-4">Proof</th>
              </tr>
            </thead>
            <tbody>
              {(runs ?? []).map((r) => {
                const active = r.run_id === run?.run_id;
                return (
                  <tr key={r.run_id} onClick={() => setSelected(r.run_id)} aria-selected={active}
                    className={`cursor-pointer border-t border-line transition-colors duration-150 hover:bg-panel ${active ? "bg-panel" : ""}`}>
                    <td className="py-2.5">
                      <button type="button" onClick={() => setSelected(r.run_id)} className={`text-left ${active ? "text-marigold" : ""}`}>
                        {ago(r.started_at)}
                      </button>
                    </td>
                    <td className="text-muted">{r.mode === "upload" ? "Upload" : "Product change"}</td>
                    <td className="num text-right">{n(r.users_in)}</td>
                    <td className="num text-right">{n(r.naive_pairs)}</td>
                    <td className="num text-right">{n(r.classes)}</td>
                    <td className="num text-right">{n(r.llm_calls)}</td>
                    <td className="num text-right">{n(r.matches_new)}</td>
                    <td className="num text-right">{n(r.emails_sent)}</td>
                    <td className="num text-right">{r.seconds != null ? `${r.seconds} s` : "-"}</td>
                    <td className="pl-4">
                      {r.status === "failed" ? <XCircle size={18} className="text-danger" aria-label="failed" />
                        : r.correctness_ok ? <SealCheck size={18} weight="fill" className="text-leaf" aria-label="verified against brute force" />
                        : <span className="text-muted">-</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="mt-16 grid gap-12 lg:grid-cols-2">
        <CrawlSection crawl={crawl} />
        <ErrorsSection errors={errors} />
      </div>

      <UploadSection onDone={refresh} />
    </div>
  );
}

function CrawlSection({ crawl }: { crawl: CrawlHealth | null }) {
  const statuses = ["ok", "unchanged", "fixture", "blocked", "robots_disallowed", "failed"];
  const label: Record<string, string> = { ok: "Read", unchanged: "Unchanged", fixture: "Saved copy", blocked: "Blocked", robots_disallowed: "Disallowed", failed: "Failed" };
  const channels = [...new Set(crawl?.products.map((p) => p.channel) ?? [])];
  return (
    <section aria-labelledby="crawl-title">
      <h2 id="crawl-title" className="text-lg font-medium">Lender crawl</h2>
      <p className="mt-1 text-sm text-muted">
        {crawl?.latest_run ? `Last read ${ago(crawl.latest_run.started_at)}. Pages that block bots are skipped, never bypassed.` : "Loading"}
      </p>
      <table className="mt-4 w-full border-collapse text-sm">
        <thead className="text-left text-xs text-muted">
          <tr className="[&_th]:pb-2 [&_th]:font-normal"><th>Source</th><th className="text-right">Products</th><th className="text-right">Verified</th><th className="text-right">Lenders</th><th className="pl-6">Pages</th></tr>
        </thead>
        <tbody>
          {channels.map((ch) => {
            const p = crawl!.products.find((x) => x.channel === ch)!;
            const pages = crawl!.pages.filter((x) => x.channel === ch);
            return (
              <tr key={ch} className="border-t border-line">
                <td className="py-2.5">{CHANNEL_LABEL[ch]}</td>
                <td className="num text-right">{p.products}</td>
                <td className="num text-right">{p.verified}</td>
                <td className="num text-right">{p.lenders}</td>
                <td className="pl-6 text-muted">
                  {statuses.filter((s) => pages.some((x) => x.status === s))
                    .map((s) => `${pages.find((x) => x.status === s)!.pages} ${label[s].toLowerCase()}`).join(", ")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function ErrorsSection({ errors }: { errors: WorkflowError[] | null }) {
  return (
    <section aria-labelledby="errors-title">
      <h2 id="errors-title" className="text-lg font-medium">Workflow errors</h2>
      <p className="mt-1 text-sm text-muted">Recorded by the error workflow; the first of each burst is emailed to the operator.</p>
      {errors && errors.length === 0 && <p className="mt-6 flex items-center gap-2 text-sm"><CheckCircle size={18} className="text-leaf" aria-hidden />No failures recorded.</p>}
      <ul className="mt-4 grid gap-0">
        {(errors ?? []).slice(0, 6).map((e) => (
          <li key={e.id} className="border-t border-line py-3 text-sm">
            <p className="flex justify-between gap-4"><span>{e.workflow}{e.node && <span className="text-muted">, at {e.node}</span>}</span><span className="shrink-0 text-muted">{ago(e.created_at)}</span></p>
            <p className="mt-1 line-clamp-2 text-muted">{e.message}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

type UploadState = { phase: "idle" } | { phase: "sending"; name: string } | { phase: "tracking"; name: string; jobId: string; progress?: UploadProgress } | { phase: "error"; message: string };

function UploadSection({ onDone }: { onDone: () => void }) {
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (state.phase !== "tracking") return;
    const finished = state.progress?.job.status === "FAILED" || state.progress?.job.match_status === "DONE" || state.progress?.job.match_status === "FAILED";
    if (finished) {
      onDone();
      return;
    }
    const id = window.setTimeout(async () => {
      try {
        const progress = await api.upload(state.jobId);
        setState((s) => (s.phase === "tracking" ? { ...s, progress } : s));
      } catch {
        /* transient: try again on the next tick */
      }
    }, 1500);
    return () => window.clearTimeout(id);
  }, [state, onDone]);

  async function choose(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setState({ phase: "sending", name: file.name });
    try {
      const ticket = await api.createUpload(file.name);
      if (file.size > ticket.max_bytes) throw new ApiError(413, "That file is larger than 50 MB.");
      const form = new FormData();
      Object.entries(ticket.upload.fields).forEach(([k, v]) => form.append(k, v));
      form.append("file", new Blob([file], { type: "text/csv" }), file.name);
      const res = await fetch(ticket.upload.url, { method: "POST", body: form });
      if (!res.ok) throw new ApiError(res.status, "The file was refused by storage. Check it is a CSV under 50 MB.");
      setState({ phase: "tracking", name: file.name, jobId: ticket.job_id });
    } catch (err) {
      setState({ phase: "error", message: err instanceof Error ? err.message : "The upload failed." });
    }
  }

  const p = state.phase === "tracking" ? state.progress : undefined;
  return (
    <section aria-labelledby="upload-title" className="mt-16 border-t border-line pt-10">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div>
          <h2 id="upload-title" className="text-lg font-medium">Upload users</h2>
          <p className="mt-1 max-w-[60ch] text-sm text-muted">
            A CSV with user_id, email, monthly_income, credit_score, employment_status and age. It goes straight to
            storage, then through validation, matching and email, like the runs above. Emails only go to test inboxes.
          </p>
        </div>
        <input ref={input} type="file" accept=".csv,text/csv" onChange={choose} className="sr-only" id="csv" />
        <button type="button" onClick={() => input.current?.click()} disabled={state.phase === "sending"}
          className="inline-flex h-10 items-center gap-2 rounded-[var(--radius-ctl)] border border-line-strong px-4 text-sm hover:bg-raise disabled:opacity-60">
          <UploadSimple size={16} aria-hidden /> Choose a CSV
        </button>
      </div>

      {state.phase !== "idle" && (
        <div className="mt-6 rounded-[var(--radius-ctl)] border border-line bg-panel p-5 text-sm" aria-live="polite">
          {state.phase === "error" ? (
            <p className="flex items-center gap-2 text-danger"><WarningCircle size={16} aria-hidden /> {state.message}</p>
          ) : (
            <>
              <p className="flex items-center gap-2 font-medium"><FileCsv size={18} aria-hidden /> {state.name}</p>
              <ul className="mt-4 grid gap-2 sm:grid-cols-4">
                <Step done={state.phase === "tracking"} active={state.phase === "sending"} label="Uploaded" />
                <Step done={!!p && ["COMPLETED"].includes(p.job.status)} active={!!p && p.job.status === "PROCESSING"} failed={p?.job.status === "FAILED"}
                  label={p?.job.total_rows != null ? `${n(p.job.inserted)} new, ${n(p.job.updated)} changed, ${n(p.job.rejected)} rejected` : "Validated"} />
                <Step done={p?.job.match_status === "DONE"} active={p?.job.match_status === "RUNNING"} failed={p?.job.match_status === "FAILED"}
                  label={p?.match_run?.matches_new != null ? `${n(p.match_run.matches_new)} matches` : "Matched"} />
                <Step done={p?.job.match_status === "DONE" && !!p.match_run} label={p?.match_run?.emails_sent != null ? `${n(p.match_run.emails_sent)} emails` : "Notified"} />
              </ul>
              {p?.job.error && <p className="mt-3 text-danger">{p.job.error}</p>}
              {p && p.rejects.length > 0 && (
                <p className="mt-3 text-muted">First rejected rows: {p.rejects.slice(0, 3).map((r) => `line ${r.row_number} (${r.reason})`).join(", ")}</p>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function Step({ label, done, active, failed }: { label: string; done?: boolean; active?: boolean; failed?: boolean }) {
  return (
    <li className="flex items-center gap-2">
      {failed ? <XCircle size={18} className="text-danger" aria-hidden /> : done ? <CheckCircle size={18} weight="fill" className="text-marigold" aria-hidden />
        : active ? <CircleNotch size={18} className="animate-spin text-marigold" aria-hidden /> : <span aria-hidden className="ml-0.5 size-3.5 rounded-full border border-line-strong" />}
      <span className={done || active ? "text-text" : "text-muted"}>{label}</span>
    </li>
  );
}
