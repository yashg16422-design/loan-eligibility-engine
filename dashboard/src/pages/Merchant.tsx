// The merchant console: bulk CSV uploads and single lookups for a signed-in account, the
// measured engine numbers, analytics of each upload, and the extras (history, runs, retries)
// one click away. Everyone shares one database, so each account sees only its own uploads.
import { FileCsv, SealCheck, SignOut, UploadSimple, WarningCircle, XCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { auth } from "../api/auth";
import { api, ApiError } from "../api/client";
import type { Analytics, CrawlHealth, Run, UploadRecord, WorkflowError } from "../api/types";
import { AnalyticsGrid } from "../components/AnalyticsGrid";
import { EmailPreviews } from "../components/EmailPreviews";
import { WaitPanel } from "../components/WaitPanel";
import { WorkflowMap } from "../components/WorkflowMap";
import { CHANNEL_LABEL } from "../lib/offers";
import { useUpload } from "../lib/upload";
import { useIsAdmin, useSignedIn } from "../lib/useAccount";
import { HBars } from "../ui/charts";
import { ConfirmDelete } from "../ui/Confirm";
import { Disclosure } from "../ui/Disclosure";
import { OnThisPage } from "../ui/OnThisPage";
import { Select } from "../ui/Select";
import { SignInFlow } from "./Account";
import { CheckForm } from "./Check";

const n = (v: number | null | undefined) => (v == null ? "-" : new Intl.NumberFormat("en-IN").format(v));

function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

const SECTIONS = [
  { id: "workspace", label: "Workspace" },
  { id: "metrics", label: "Metrics" },
  { id: "analytics", label: "Analytics" },
  { id: "more", label: "History & runs" },
];

export function Merchant() {
  const email = useSignedIn();
  const admin = useIsAdmin();
  const upload = useUpload();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [crawl, setCrawl] = useState<CrawlHealth | null>(null);
  const [errors, setErrors] = useState<WorkflowError[] | null>(null);
  const [uploads, setUploads] = useState<UploadRecord[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null); // a job id from the dataset menu

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
  const refreshUploads = useCallback(async () => {
    if (!auth.email()) return setUploads(null);
    try {
      setUploads(await api.uploads());
    } catch {
      setUploads([]);
    }
  }, []);
  useEffect(() => void refresh(), [refresh]);
  useEffect(() => void refreshUploads(), [refreshUploads, email]);

  const live = upload.state.phase === "tracking" ? upload.state : null;
  useEffect(() => {
    if (live?.jobId) {
      setPicked(null); // a new upload takes over the charts
      void refreshUploads();
    }
  }, [live?.jobId, refreshUploads]);
  useEffect(() => {
    if (live?.finished) {
      void refresh();
      void refreshUploads();
    }
  }, [live?.finished, refresh, refreshUploads]);

  // The full-file run the API always lists: the measured Treasure Hunt numbers.
  const reference = runs?.find((r) => r.reference);
  const mine = useMemo(() => (uploads ?? []).filter((u) => !u.purged_at && u.users_now > 0), [uploads]);
  // Signed in, an account sees only its own data (every account starts fresh); admins can also
  // open the reference dataset; visitors who are signed out see the reference as a demo.
  const showReference = !email || admin;
  const datasets = useMemo(() => {
    const own = mine.map((u) => ({ value: u.job_id, label: `${u.original_filename ?? "users.csv"} · ${n(u.users_now)} customers · ${ago(u.created_at)}` }));
    const ref = showReference && reference?.job_id ? [{ value: reference.job_id, label: `Reference dataset · ${n(reference.users_in)} customers` }] : [];
    return [...own, ...ref.filter((r) => !own.some((o) => o.value === r.value))];
  }, [mine, reference, showReference]);
  // Charts: what you picked, else your live upload once loaded, else your latest, else (visitors
  // and admins) the reference.
  const chartJob = picked ?? (live?.finished ? live.jobId : mine[0]?.job_id ?? (showReference ? reference?.job_id ?? null : null));

  // Bring the charts into view once they have loaded, after "View" or a finished upload.
  const focusCharts = useRef(false);
  useEffect(() => {
    if (live?.finished) focusCharts.current = true;
  }, [live?.finished]);
  const goToAnalytics = useCallback(() => {
    const heading = document.getElementById("analytics-title");
    heading?.scrollIntoView({ behavior: "smooth", block: "start" });
    heading?.focus({ preventScroll: true });
  }, []);
  const onChartsLoaded = useCallback(() => {
    if (!focusCharts.current) return;
    focusCharts.current = false;
    goToAnalytics();
  }, [goToAnalytics]);

  return (
    <div className="mx-auto max-w-[1480px] px-5 pt-14 pb-20 sm:px-10 lg:pt-24 xl:grid xl:grid-cols-[minmax(0,1fr)_200px] xl:gap-16 xl:px-16">
      <div className="min-w-0">
        <header className="max-w-[900px]">
          <h1 className="text-[2.75rem] sm:text-[4.25rem]">Merchant console</h1>
          <p className="mt-6 max-w-[62ch] text-lg text-mute">
            Check your customers against every lender's published rules: a whole CSV at once, or one person at a time.
            Results are matched by the same engine consumers use, and emails only ever reach the project's test inboxes.
          </p>
          {failed && (
            <p role="alert" className="mt-5 flex items-center gap-2 text-sm text-coral">
              <WarningCircle size={16} aria-hidden /> {failed}
              <button type="button" className="underline underline-offset-4" onClick={refresh}>Try again</button>
            </p>
          )}
        </header>

        <section id="workspace" aria-label="Workspace" className="mt-16 scroll-mt-28">
          {email ? (
            <Workspace
              email={email}
              admin={admin}
              records={
                <UploadsTable uploads={uploads} admin={admin} selected={chartJob} referenceJob={reference?.job_id ?? null} onView={(id) => {
                  // Straight to Analytics: the loading bar shows there while its charts load.
                  setPicked(id);
                  window.requestAnimationFrame(goToAnalytics);
                }} onDeleted={async () => {
                  setPicked(null);
                  upload.reset();
                  await Promise.all([refresh(), refreshUploads()]);
                }} />
              }
            />
          ) : (
            <SignedOut />
          )}
        </section>

        <section id="metrics" aria-labelledby="metrics-title" className="mt-28 scroll-mt-28">
          <h2 id="metrics-title" className="text-3xl">Metrics</h2>
          <Metrics uploads={email ? uploads : null} reference={reference} crawl={crawl} runs={runs} signedIn={!!email} />
        </section>

        <section id="analytics" aria-labelledby="analytics-title" className="mt-28 scroll-mt-28">
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <h2 id="analytics-title" tabIndex={-1} className="text-3xl outline-none">Analytics</h2>
              <p className="mt-3 max-w-[62ch] text-mute">Who the customers in a dataset are, and where they qualify.</p>
            </div>
            {datasets.length > 0 && chartJob && (
              <div className="w-full sm:w-[380px]">
                <Select label="Dataset" value={chartJob} options={datasets} onChange={setPicked} />
              </div>
            )}
          </div>
          <div className="mt-10">
            {chartJob ? (
              <>
                <Charts jobId={chartJob} name={datasets.find((d) => d.value === chartJob)?.label ?? "this upload"} signedIn={!!email} onLoaded={onChartsLoaded} />
                {email && <EmailPreviews jobId={chartJob} />}
              </>
            ) : email && uploads !== null ? (
              <div className="border border-dashed border-line-hi p-10">
                <p className="text-xl font-light">Your analytics appear here after your first upload.</p>
                <p className="mt-3 max-w-[60ch] text-sm text-mute">
                  Every account starts with an empty workspace. Upload a CSV above and its charts form as the run reports:
                  who your customers are, how many qualify, and where.
                </p>
              </div>
            ) : (
              <LoadingBar label="Loading analytics" />
            )}
          </div>
        </section>

        <section id="more" aria-labelledby="more-title" className="mt-28 scroll-mt-28">
          <h2 id="more-title" className="text-3xl">History &amp; runs</h2>
          <div className="mt-8 border-t border-line">
            <Disclosure title="Matching runs" meta={runs ? `${n(runs.length)} runs` : undefined}>
              <RunsTable runs={runs} />
            </Disclosure>
            <Disclosure title="Workflows, retries and errors" meta={errors ? `${n(errors.length)} failures recorded` : undefined}>
              <Workflows crawl={crawl} reference={reference} runs={runs} errors={errors} />
            </Disclosure>
          </div>
        </section>
      </div>
      <OnThisPage sections={SECTIONS} />
    </div>
  );
}

// ---------------------------------------------------------------- workspace

function SignedOut() {
  return (
    <div className="grid border border-line lg:grid-cols-[minmax(0,1fr)_minmax(0,460px)]">
      <div className="border-b border-line p-8 sm:p-10 lg:border-r lg:border-b-0">
        <h2 className="text-2xl">Sign in to upload</h2>
        <p className="mt-4 max-w-[52ch] text-mute">
          Uploads belong to your account. Several people test this console on one shared database, so you only ever see,
          and delete, the uploads you made.
        </p>
        <dl className="mt-10 grid gap-6 sm:grid-cols-2">
          {[
            ["Bulk upload", "A CSV of customers, matched against every lender and emailed per customer."],
            ["Single lookup", "One customer's four numbers, with their full results."],
            ["Your records", "Every upload kept as its own record, with charts. Delete one to run it again."],
            ["Same engine", "The pipeline the measured numbers below come from."],
          ].map(([t, d]) => (
            <div key={t}>
              <dt className="label text-fg">{t}</dt>
              <dd className="mt-2 text-sm text-mute">{d}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="bg-panel p-8 sm:p-10">
        <SignInFlow embedded onDone={() => document.getElementById("workspace")?.scrollIntoView({ behavior: "smooth" })} />
      </div>
    </div>
  );
}

function Workspace({ email, admin, records }: { email: string; admin: boolean; records: React.ReactNode }) {
  // `records` is the "Your uploads" row (collapsible), rendered under the bulk tool.
  const [tool, setTool] = useState<"bulk" | "single">("bulk");
  return (
    <div className="min-w-0 border border-line">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-6 sm:px-8">
        <div role="tablist" aria-label="Tool" className="flex gap-8">
          {([["bulk", "Bulk upload"], ["single", "Single lookup"]] as const).map(([key, label]) => (
            <button key={key} role="tab" type="button" aria-selected={tool === key} onClick={() => setTool(key)}
              className={`-mb-px border-b py-5 text-[0.95rem] transition-colors duration-150 ${
                tool === key ? "border-fg text-fg" : "border-transparent text-mute hover:text-fg"
              }`}>
              {label}
            </button>
          ))}
        </div>
        <p className="flex items-center gap-4 py-3 text-sm text-mute">
          <span className="max-w-[260px] truncate">{email}{admin && <span className="label ml-2 text-fg">admin</span>}</span>
          <button type="button" onClick={() => void auth.signOut()} className="inline-flex items-center gap-1.5 hover:text-fg">
            <SignOut size={15} aria-hidden /> Sign out
          </button>
        </p>
      </div>
      <div className="p-6 sm:p-8">
        {tool === "bulk" ? (
          <div className="grid gap-12 [&>*]:min-w-0">
            <Bulk />
            <div className="border-t border-line">{records}</div>
          </div>
        ) : (
          <Single />
        )}
      </div>
    </div>
  );
}

function Single() {
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,560px)_minmax(0,1fr)]">
      <CheckForm submitLabel="Look up customer" />
      <div className="text-sm text-mute lg:pt-2">
        <h3 className="text-lg font-light text-fg">One customer, full results</h3>
        <p className="mt-3 max-w-[48ch]">
          The four numbers go through the same pipeline as a CSV row and open that customer's matches: top five, every
          lender they qualify for, and the exact rule that rules out the rest. Usually about ten seconds.
        </p>
      </div>
    </div>
  );
}

function Bulk() {
  const upload = useUpload();
  const p = upload.state.phase === "tracking" ? upload.state.progress : undefined;
  const run = p?.match_run;
  return (
    <div className="grid gap-8 [&>*]:min-w-0">
      <DropZone />
      <WorkflowMap state={upload.state} />
      {(upload.state.phase === "sending" || (upload.state.phase === "tracking" && !upload.state.finished)) && (
        <WaitPanel state={upload.state} />
      )}
      {p && (
        <div className="grid gap-px border border-line bg-line lg:grid-cols-2 [&>*]:min-w-0" aria-live="polite">
          <section className="bg-bg p-7">
            <h3 className="label">Rows in this file</h3>
            <div className="mt-6">
              {p.job.total_rows == null ? (
                <p className="text-sm text-mute">Waiting for the file to be validated.</p>
              ) : (
                <HBars rows={[
                  { label: "New customers", value: p.job.inserted ?? 0, color: "var(--color-acc-2)" },
                  { label: "Changed customers", value: p.job.updated ?? 0, color: "var(--color-teal)" },
                  { label: "Unchanged (already up to date)", value: p.job.unchanged ?? 0, color: "var(--color-dim)" },
                  { label: "Rejected (reasons below)", value: p.job.rejected ?? 0, color: "var(--color-coral)" },
                ]} />
              )}
              {p.rejects.length > 0 && (
                <ul className="mt-6 grid gap-1 text-sm text-mute">
                  {p.rejects.slice(0, 4).map((r) => (
                    <li key={r.row_number}><span className="num text-coral">line {r.row_number}</span> {r.reason.replace(/_/g, " ")}</li>
                  ))}
                </ul>
              )}
            </div>
          </section>
          <section className="bg-bg p-7">
            <h3 className="label">How the engine narrowed the work</h3>
            <div className="mt-6">
              {run && p.job.match_status === "DONE" ? (
                <HBars log rows={[
                  { label: "Customer and product pairs", value: run.naive_pairs ?? 0, color: "var(--color-dim)" },
                  { label: "Pairs passing published rules", value: run.pairs_after_sql ?? 0, color: "var(--color-amber)" },
                  { label: "Classes (customers who get identical answers)", value: run.classes ?? 0, color: "var(--color-peri)" },
                  { label: "AI calls", value: run.llm_calls ?? 0, color: "var(--color-peri)" },
                  { label: "New matches", value: run.matches_new ?? 0, color: "var(--color-acc)" },
                ]} />
              ) : (
                <p className="text-sm text-mute">Appears when matching finishes, usually a few seconds after loading.</p>
              )}
            </div>
          </section>
        </div>
      )}
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
      className={`flex flex-wrap items-center justify-between gap-6 border border-dashed p-8 transition-colors duration-150 ${over ? "border-fg bg-panel" : "border-line-hi"}`}
    >
      <div className="flex items-start gap-5">
        <FileCsv size={30} weight="light" className="mt-0.5 shrink-0 text-fg" aria-hidden />
        <div>
          <h3 className="text-xl font-light">Drop a customers CSV, or choose one</h3>
          <p className="mt-2 max-w-[64ch] text-sm text-mute">
            A .csv with a header row: user_id, name, email, monthly_income, credit_score, employment_status, age. Up to
            50 MB, 10 uploads per account a day. Rows that fail a check are set aside with the reason; the rest are matched.
          </p>
          {state.phase === "error" && (
            <p role="alert" className="mt-4 flex items-start gap-2 text-sm text-coral">
              <WarningCircle size={18} className="mt-0.5 shrink-0" aria-hidden />
              <span>{state.name ? <b className="font-medium">{state.name}: </b> : null}{state.message}</span>
            </p>
          )}
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

// ---------------------------------------------------------------- metrics + charts

function Metrics({
  uploads,
  reference,
  crawl,
  runs,
  signedIn,
}: {
  uploads: UploadRecord[] | null;
  reference: Run | undefined;
  crawl: CrawlHealth | null;
  runs: Run[] | null;
  signedIn: boolean;
}) {
  const live = (uploads ?? []).filter((u) => !u.purged_at);
  const sum = (k: "users_now" | "matches" | "emails_sent") => live.reduce((s, u) => s + u[k], 0);
  const products = crawl?.products.reduce((s, p) => s + p.products, 0);
  const verified = crawl?.products.reduce((s, p) => s + p.verified, 0);
  const emailsAll = runs?.reduce((s, r) => s + (r.emails_sent ?? 0), 0);
  const yours: Cell[] = [
    { label: "Uploads", value: n(live.length), note: "files in your workspace" },
    { label: "Customers", value: n(sum("users_now")), note: "loaded from your files" },
    { label: "Matches", value: n(sum("matches")), note: "eligible or may qualify", tone: "text-acc" },
    { label: "Emails sent", value: n(sum("emails_sent")), note: "to the project's test inboxes" },
  ];
  const engine: Cell[] = [
    { label: "Lender products", value: n(products), note: `${n(verified)} with criteria verified on the page`, tone: "text-amber" },
    { label: "Pairs to check", value: n(reference?.naive_pairs), note: `${n(reference?.users_in)} customers in the reference run` },
    { label: "Decided as classes", value: n(reference?.classes), note: "customers who get identical answers", tone: "text-peri" },
    {
      label: "AI calls",
      value: n(reference?.llm_calls),
      note: reference?.llm_cache_hits ? `${n(reference.llm_cache_hits)} answers reused from cache` : "for the whole file",
      tone: "text-peri",
    },
    {
      label: "Proof",
      value: reference?.correctness_ok ? "Exact" : "-",
      note: reference?.correctness_ok ? "same result as checking every pair" : "waiting for a reference run",
      tone: reference?.correctness_ok ? "text-acc" : undefined,
    },
    { label: "Emails, all runs", value: n(emailsAll), note: "recent runs, test inboxes only" },
  ];
  return (
    <div className="mt-10 grid gap-10">
      {signedIn && <Readouts title="Your workspace" cells={yours} cols="lg:grid-cols-4" />}
      <Readouts title="Engine, shared by every account" cells={engine} cols="lg:grid-cols-3" />
    </div>
  );
}

type Cell = { label: string; value: string; note: string; tone?: string };

function Readouts({ title, cells, cols }: { title: string; cells: Cell[]; cols: string }) {
  return (
    <div>
      <h3 className="label text-fg">{title}</h3>
      <dl className={`mt-4 grid grid-cols-2 gap-px border border-line bg-line ${cols}`}>
        {cells.map((c) => (
          <div key={c.label} className="bg-bg p-5 sm:p-7">
            <dt className="label">{c.label}</dt>
            <dd className={`num mt-4 text-[1.6rem] leading-none font-light tracking-[-0.02em] sm:mt-5 sm:text-[2.25rem] ${c.tone ?? "text-fg"}`}>{c.value}</dd>
            <dd className="mt-3 text-sm text-mute">{c.note}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Charts({ jobId, name, signedIn, onLoaded }: { jobId: string; name: string; signedIn: boolean; onLoaded: () => void }) {
  const [data, setData] = useState<{ jobId: string; analytics: Analytics } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [nonce, setNonce] = useState(0); // "Try again" after the automatic retries
  useEffect(() => {
    let gone = false;
    let retry = 0;
    setFailed(null);
    (signedIn ? api.uploadAnalytics(jobId) : api.analytics(jobId))
      .then((a) => !gone && setData({ jobId, analytics: a }))
      .catch((err) => {
        if (gone) return;
        // A busy database (a run is writing matches) can make the first computation slow:
        // try again by itself a few times before showing an error.
        if (attempt < 3 && !(err instanceof ApiError && [401, 403, 404].includes(err.status))) {
          retry = window.setTimeout(() => setAttempt((n) => n + 1), 3000 * (attempt + 1));
        } else {
          setFailed(err instanceof Error ? err.message : "The charts could not be loaded.");
        }
      });
    return () => {
      gone = true;
      window.clearTimeout(retry);
    };
  }, [jobId, signedIn, attempt, nonce]);
  useEffect(() => setAttempt(0), [jobId]);
  const ready = data?.jobId === jobId;
  useEffect(() => {
    if (ready) onLoaded();
  }, [ready, onLoaded]);
  if (failed)
    return (
      <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-coral">
        <WarningCircle size={16} aria-hidden /> {failed}
        <button type="button" className="underline underline-offset-4" onClick={() => (setAttempt(0), setNonce((x) => x + 1))}>Try again</button>
      </p>
    );
  if (!ready || !data)
    return <LoadingBar label={attempt ? `Still computing the analytics for ${name}: retrying (${attempt} of 3)` : `Loading analytics for ${name}`} />;
  return <AnalyticsGrid data={data.analytics} />;
}

/** A thin indeterminate bar with a label: something is loading, and what. */
function LoadingBar({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="border border-line p-8">
      <p className="label">{label}</p>
      <div aria-hidden className="mt-5 h-px w-full overflow-hidden bg-line">
        <div className="loading-bar h-full w-1/3 bg-fg" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- extras

function uploadState(u: UploadRecord): { text: string; tone: string } {
  if (u.purged_at) return { text: "Data deleted", tone: "text-mute" };
  if (u.status === "FAILED") return { text: "Failed", tone: "text-coral" };
  if (u.status === "AWAITING_UPLOAD") return { text: "Waiting for file", tone: "text-mute" };
  if (u.status === "PROCESSING") return { text: "Loading", tone: "text-amber" };
  if (u.match_status === "FAILED") return { text: "Matching failed", tone: "text-coral" };
  if (u.match_status !== "DONE") return { text: "Matching", tone: "text-peri" };
  return { text: "Done", tone: "text-acc" };
}

function UploadsTable({
  uploads,
  admin,
  selected,
  referenceJob,
  onView,
  onDeleted,
}: {
  uploads: UploadRecord[] | null;
  admin: boolean;
  selected: string | null;
  referenceJob: string | null;
  onView: (jobId: string) => void;
  onDeleted: () => Promise<void>;
}) {
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const report = async (work: () => Promise<string>) => {
    try {
      setResult({ ok: true, text: await work() });
      await onDeleted();
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : "Nothing was deleted. Try again." });
    }
  };
  const live = (uploads ?? []).filter((u) => !u.purged_at && u.users_now > 0).length;
  return (
    <Disclosure title="Your uploads" meta={uploads === null ? "loading" : `${n(uploads.length)} records, ${n(live)} with customers`}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="max-w-[72ch] text-sm text-mute">
          Each CSV is its own record, and every account starts with an empty workspace. Deleting an upload removes its
          customers, matches and email records, so the file can be uploaded again and run as new. Products, run history and
          accounts stay.{admin && " As an admin you also see other accounts' uploads."}
        </p>
        <span className="flex flex-wrap items-center gap-3">
          <ConfirmDelete small label="Reset my workspace" question="Delete the customers of every upload you made?"
            onConfirm={() => report(async () => {
              const r = await api.purgeUploads("mine");
              return `Your workspace is empty again: ${n(r.deleted_users)} customers from ${n(r.uploads)} uploads deleted.`;
            })} />
          {admin && (
            <ConfirmDelete small label="Delete every account's uploads" question="Delete every customer that came from any account's CSV?"
              onConfirm={() => report(async () => {
                const r = await api.purgeUploads("all");
                return `Deleted ${n(r.deleted_users)} customers from ${n(r.uploads)} uploads across all accounts.`;
              })} />
          )}
        </span>
      </div>
      {result && <p role="status" className={`mt-4 text-sm ${result.ok ? "text-acc" : "text-coral"}`}>{result.text}</p>}
      <div className="mt-6 overflow-x-auto border border-line">
        <table className="w-full min-w-[960px] border-collapse text-sm">
          <thead className="text-left">
            <tr className="[&_th]:px-5 [&_th]:py-4 [&_th]:font-normal [&_th]:whitespace-nowrap [&_th]:label">
              <th>File</th><th className="text-right">Rows</th><th className="text-right">New</th><th className="text-right">Changed</th>
              <th className="text-right">Rejected</th><th className="text-right">Customers</th><th className="text-right">Matches</th>
              <th className="text-right">Emails</th><th>Status</th><th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {uploads === null ? (
              <tr><td colSpan={10} className="h-20 bg-panel" aria-busy="true" /></tr>
            ) : uploads.length === 0 ? (
              <tr><td colSpan={10} className="border-t border-line px-5 py-8 text-mute">No uploads yet. Choose a CSV in the workspace and it appears here as it runs.</td></tr>
            ) : (
              uploads.map((u) => {
                const state = uploadState(u);
                return (
                  <tr key={u.job_id} className={`border-t border-line align-middle [&_td]:px-5 [&_td]:py-4 [&_td]:whitespace-nowrap ${selected === u.job_id ? "bg-panel-2" : ""}`}>
                    <td>
                      <span className="block max-w-[260px] truncate">
                        {u.original_filename ?? "users.csv"}
                        {u.job_id === referenceJob && <span className="label ml-2 text-fg">reference</span>}
                      </span>
                      <span className="label normal-case tracking-normal">{ago(u.created_at)}</span>
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
                          <button type="button" onClick={() => onView(u.job_id)} aria-pressed={selected === u.job_id}
                            className={`btn btn-ghost min-h-9 px-3 text-sm ${selected === u.job_id ? "border-fg" : ""}`}>View</button>
                        )}
                        {!u.purged_at && u.users_now > 0 && (
                          <ConfirmDelete small label="Delete"
                            question={u.job_id === referenceJob
                              ? `This is the reference dataset behind the default charts. Delete its ${n(u.users_now)} customers?`
                              : `Delete ${n(u.users_now)} customers?`}
                            onConfirm={() => report(async () => {
                              const r = await api.purgeUpload(u.job_id);
                              return `Deleted ${n(r.deleted_users)} customers from ${u.original_filename ?? "that upload"}. Upload it again to run it as new.`;
                            })} />
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
    </Disclosure>
  );
}

function RunsTable({ runs }: { runs: Run[] | null }) {
  return (
    <div className="overflow-x-auto border border-line">
      <table className="w-full min-w-[880px] border-collapse text-sm">
        <thead className="text-left">
          <tr className="[&_th]:px-5 [&_th]:py-4 [&_th]:font-normal [&_th]:whitespace-nowrap [&_th]:label">
            <th>When</th><th>Trigger</th><th className="text-right">Customers</th><th className="text-right">Pairs</th>
            <th className="text-right">Classes</th><th className="text-right">AI calls</th><th className="text-right">New matches</th>
            <th className="text-right">Emails</th><th className="text-right">Time</th><th>Proof</th>
          </tr>
        </thead>
        <tbody>
          {(runs ?? []).map((r) => (
            <tr key={r.run_id} className="border-t border-line [&_td]:px-5 [&_td]:py-3.5 [&_td]:whitespace-nowrap">
              <td>{ago(r.started_at)}</td>
              <td className="text-mute">
                {r.mode === "upload" ? "Upload or check" : "Product change"}
                {r.reference && <span className="label ml-2 text-fg">reference</span>}
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
  );
}

function Workflows({ crawl, reference, runs, errors }: { crawl: CrawlHealth | null; reference: Run | undefined; runs: Run[] | null; errors: WorkflowError[] | null }) {
  const rows: { name: string; color: string; trigger: string; facts: string[] }[] = [
    {
      name: "A · Loan discovery", color: "var(--color-amber)", trigger: "Daily at 06:00 IST, and on demand",
      facts: crawl ? [
        `${n(crawl.products.reduce((s, p) => s + p.products, 0))} products: ${crawl.products.map((p) => `${CHANNEL_LABEL[p.channel]} ${p.products}`).join(", ")}`,
        crawl.latest_run ? `Last crawl ${ago(crawl.latest_run.started_at)}` : "No crawl yet",
      ] : [],
    },
    {
      name: "B · Matching", color: "var(--color-peri)", trigger: "Every upload (webhook), a 10-minute sweeper, and A's product changes",
      facts: [
        reference ? `Reference: ${n(reference.naive_pairs)} pairs → ${n(reference.classes)} classes → ${n(reference.llm_calls)} AI calls` : "",
        "Retries: a failed job is retried up to 3 times, 10 minutes apart; a run stuck for 30 minutes is closed",
        "A run whose proof fails stops before any email is sent",
      ].filter(Boolean),
    },
    {
      name: "C · Notification", color: "var(--color-acc)", trigger: "Right after each matching run",
      facts: runs ? [
        `${n(runs.reduce((s, r) => s + (r.emails_sent ?? 0), 0))} emails sent in recent runs; ${n(runs.reduce((s, r) => s + (r.emails_skipped_demo ?? 0), 0))} held by the demo cap`,
        "Personalised best pick per customer via AWS SES, test inboxes only",
      ] : [],
    },
    {
      name: "E · Error handler", color: "var(--color-coral)", trigger: "Whenever A, B or C fails",
      facts: errors ? [
        `${n(errors.length)} failures recorded${errors[0] ? `; latest: ${errors[0].workflow}, ${ago(errors[0].created_at)}` : ""}`,
        "Each burst emails the operator once",
      ] : [],
    },
  ];
  return (
    <ul className="grid gap-px border border-line bg-line md:grid-cols-2">
      {rows.map((w) => (
        <li key={w.name} className="box tick bg-bg p-7" style={{ ["--tick" as string]: w.color }}>
          <h4 className="text-lg font-light">{w.name}</h4>
          <p className="label mt-2 normal-case tracking-normal">{w.trigger}</p>
          <ul className="mt-5 grid gap-2 text-sm text-mute">
            {w.facts.map((f) => <li key={f}>{f}</li>)}
          </ul>
        </li>
      ))}
    </ul>
  );
}
