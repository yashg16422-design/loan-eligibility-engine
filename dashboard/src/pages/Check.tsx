import { CheckCircle, CircleNotch, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, session } from "../api/client";
import type { Employment } from "../api/types";
import { EMPLOYMENT_LABEL } from "../lib/format";
import { navigate } from "../router";

type Stage = "idle" | "queued" | "loaded" | "matched" | "failed";

// The real path a check travels (the same one a 10,000-row upload takes).
const STEPS: { key: Exclude<Stage, "idle" | "failed">; title: string; detail: string }[] = [
  { key: "queued", title: "Received", detail: "Your details are written as a one-row file and queued." },
  { key: "loaded", title: "Validated", detail: "The same rules as a bulk upload check every value." },
  { key: "matched", title: "Matched", detail: "Every lender's criteria are evaluated for your profile." },
];
const ORDER: Stage[] = ["idle", "queued", "loaded", "matched"];

export function Check() {
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const started = useRef(0);
  const busy = stage !== "idle" && stage !== "failed";

  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => setElapsed((Date.now() - started.current) / 1000), 100);
    return () => window.clearInterval(id);
  }, [busy]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setError(null);
    started.current = Date.now();
    setElapsed(0);
    setStage("queued");
    try {
      const { token } = await api.check({
        name: String(form.get("name") ?? ""),
        monthly_income: Number(form.get("income")),
        credit_score: Number(form.get("score")),
        age: Number(form.get("age")),
        employment_status: form.get("employment") as Employment,
      });
      session.set(token);
      await waitForMatches(setStage);
      window.setTimeout(() => navigate("dashboard"), 650); // let "Matched" register
    } catch (err) {
      setStage("failed");
      setError(err instanceof ApiError ? err.message : "The check could not start. Try again in a moment.");
    }
  }

  return (
    <div className="mx-auto grid max-w-[1240px] gap-12 px-4 pt-12 pb-16 sm:px-6 lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-20 lg:pt-20">
      <section aria-labelledby="check-title" className="max-w-[560px]">
        <h1 id="check-title" className="text-3xl font-semibold leading-tight">
          See which personal loans you qualify for, before you apply.
        </h1>
        <p className="mt-3 max-w-[52ch] text-muted">
          Four numbers, checked against the criteria 26 lenders publish. Applying blind is how rejections end up on
          your credit report.
        </p>

        <form onSubmit={submit} className="mt-10 grid gap-6" aria-describedby={error ? "check-error" : undefined}>
          <div className="grid gap-6 sm:grid-cols-2">
            <Field label="Monthly income" hint="Take-home, in rupees">
              <Prefixed prefix="₹">
                <input name="income" required inputMode="numeric" pattern="[0-9]*" min={1} placeholder="52000"
                  disabled={busy} className={inputCls + " pl-7"} />
              </Prefixed>
            </Field>
            <Field label="Credit score" hint="CIBIL, between 300 and 900">
              <input name="score" required inputMode="numeric" pattern="[0-9]*" placeholder="760" disabled={busy}
                className={inputCls} />
            </Field>
            <Field label="Age" hint="In years">
              <input name="age" required inputMode="numeric" pattern="[0-9]*" placeholder="31" disabled={busy}
                className={inputCls} />
            </Field>
            <Field label="First name" hint="Optional, to greet you">
              <input name="name" maxLength={60} autoComplete="given-name" disabled={busy} className={inputCls} />
            </Field>
          </div>

          <fieldset disabled={busy}>
            <legend className="text-sm font-medium">How you earn</legend>
            <div className="mt-2 inline-flex rounded-full border border-line bg-panel p-1" role="radiogroup">
              {(Object.keys(EMPLOYMENT_LABEL) as Employment[]).map((value, i) => (
                <label key={value} className="relative cursor-pointer">
                  <input type="radio" name="employment" value={value} defaultChecked={i === 0}
                    className="peer absolute inset-0 cursor-pointer opacity-0" />
                  <span className="block rounded-full px-4 py-1.5 text-sm text-muted transition-colors duration-150 peer-checked:bg-marigold peer-checked:text-marigold-ink peer-focus-visible:outline-2 peer-focus-visible:outline-marigold">
                    {EMPLOYMENT_LABEL[value]}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="flex flex-wrap items-center gap-4">
            <button type="submit" disabled={busy}
              className="inline-flex h-11 items-center gap-2 rounded-[var(--radius-ctl)] bg-marigold px-5 font-medium text-marigold-ink transition-transform duration-150 active:scale-[0.98] disabled:cursor-wait disabled:opacity-70">
              {busy && <CircleNotch size={18} className="animate-spin" aria-hidden />}
              {busy ? "Checking" : "Check my eligibility"}
            </button>
            <p className="text-xs text-muted">No email, no phone number, no credit enquiry.</p>
          </div>
          {error && (
            <p id="check-error" role="alert" className="flex items-start gap-2 text-sm text-danger">
              <WarningCircle size={18} className="mt-0.5 shrink-0" aria-hidden />
              {error}
            </p>
          )}
        </form>
      </section>

      <aside aria-label="Progress of your check" className="lg:pt-2">
        <h2 className="text-sm font-medium">What happens when you press check</h2>
        <ol className="mt-5 grid gap-0">
          {STEPS.map((step, i) => {
            const state = ORDER.indexOf(stage) > ORDER.indexOf(step.key) || stage === "matched" ? "done"
              : stage === step.key ? "active" : "todo";
            return (
              <li key={step.key} className="relative grid grid-cols-[24px_1fr] gap-3 pb-7 last:pb-0">
                {i < STEPS.length - 1 && (
                  <span aria-hidden className={`absolute top-6 left-[11px] h-[calc(100%-24px)] w-px transition-colors duration-300 ${state === "done" ? "bg-marigold" : "bg-line-strong"}`} />
                )}
                <StepIcon state={state} />
                <div>
                  <p className={`text-sm font-medium ${state === "todo" ? "text-muted" : "text-text"}`}>{step.title}</p>
                  <p className="mt-0.5 text-sm text-muted">{step.detail}</p>
                </div>
              </li>
            );
          })}
        </ol>
        {stage !== "idle" && (
          <p className="mt-6 text-xs text-muted" aria-live="polite">
            {stage === "matched" ? `Done in ${elapsed.toFixed(1)} s. Opening your matches.`
              : stage === "failed" ? "Stopped." : `${elapsed.toFixed(1)} s`}
          </p>
        )}
      </aside>
    </div>
  );
}

/** Poll GET /me until Workflow B has written the matches (about 10 s end to end). */
async function waitForMatches(setStage: (s: Stage) => void): Promise<void> {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    const { body } = await api.me();
    if (body.matching === "running") setStage("loaded");
    if (body.matching === "done") return setStage("matched");
    if (body.matching === "failed") throw new ApiError(500, "Matching failed for this check. Please try again.");
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new ApiError(504, "This is taking longer than usual. Open My matches in a minute.");
}

function StepIcon({ state }: { state: "done" | "active" | "todo" }) {
  if (state === "done") return <CheckCircle size={24} weight="fill" className="text-marigold" aria-label="done" />;
  if (state === "active") return <CircleNotch size={24} className="animate-spin text-marigold" aria-label="in progress" />;
  return <span aria-hidden className="mt-1 ml-1 block size-4 rounded-full border border-line-strong" />;
}

const inputCls =
  "h-11 w-full rounded-[var(--radius-ctl)] border border-line-strong bg-panel px-3 text-text placeholder:text-muted/40 transition-colors duration-150 hover:border-muted/50 focus:border-marigold focus:outline-none disabled:opacity-60 num";

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-2">
      <span className="text-sm font-medium">{label}</span>
      {children}
      <span className="text-xs text-muted">{hint}</span>
    </label>
  );
}

function Prefixed({ prefix, children }: { prefix: string; children: React.ReactNode }) {
  return (
    <span className="relative block">
      <span aria-hidden className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted">{prefix}</span>
      {children}
    </span>
  );
}
