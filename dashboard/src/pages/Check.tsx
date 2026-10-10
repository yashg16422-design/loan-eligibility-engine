import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, session } from "../api/client";
import type { Employment } from "../api/types";
import { EMPLOYMENT_LABEL } from "../lib/format";
import { navigate } from "../router";

type Stage = "idle" | "queued" | "loaded" | "matched" | "failed";

// The real path one check travels: the same one a 10,000-row upload takes.
const STEPS: { key: Exclude<Stage, "idle" | "failed">; title: string; detail: string }[] = [
  { key: "queued", title: "Received", detail: "Your four numbers are written as a one-row file to S3." },
  { key: "loaded", title: "Validated", detail: "The same rules as a bulk upload check every value." },
  { key: "matched", title: "Matched", detail: "Every lender's published criteria are evaluated for you." },
];
const ORDER: Stage[] = ["idle", "queued", "loaded", "matched"];

export function Check() {
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [employment, setEmployment] = useState<Employment>("salaried");
  const [elapsed, setElapsed] = useState(0);
  const started = useRef(0);
  const busy = stage !== "idle" && stage !== "failed";

  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => setElapsed((Date.now() - started.current) / 1000), 200);
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
        monthly_income: Number(String(form.get("income")).replace(/[^\d]/g, "")),
        credit_score: Number(form.get("score")),
        age: Number(form.get("age")),
        employment_status: employment,
      });
      session.set(token);
      await waitForMatches(setStage);
      navigate("dashboard");
    } catch (err) {
      setStage("failed");
      setError(err instanceof ApiError ? err.message : "The check could not start. Try again in a moment.");
    }
  }

  return (
    <div className="mx-auto grid max-w-[1480px] gap-12 px-5 pt-14 pb-12 sm:px-10 xl:px-16 lg:grid-cols-[minmax(0,560px)_minmax(0,1fr)] lg:gap-24 lg:pt-20">
      <section aria-labelledby="check-title">
        <h1 id="check-title" className="text-3xl sm:text-4xl">Know your yes before you apply.</h1>
        <p className="mt-3 max-w-[50ch] text-mute">
          Four numbers, checked against every lender's published rules. No email, no phone number, no credit enquiry.
        </p>

        <form onSubmit={submit} className="box mt-8" aria-describedby={error ? "check-error" : undefined}>
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <span className="label">/check</span>
            <span className="label">ClickPar Match</span>
          </div>
          <fieldset disabled={busy} className="grid gap-5 p-4 sm:grid-cols-2">
            <Field label="Monthly income" hint="Take-home, in rupees">
              <input name="income" required inputMode="numeric" autoComplete="off" placeholder="₹48,000" className="field" />
            </Field>
            <Field label="Credit score" hint="CIBIL, 300 to 900">
              <input name="score" required inputMode="numeric" autoComplete="off" placeholder="742" className="field" />
            </Field>
            <Field label="Age" hint="In years">
              <input name="age" required inputMode="numeric" autoComplete="off" placeholder="29" className="field" />
            </Field>
            <Field label="First name" hint="Optional, to greet you">
              <input name="name" maxLength={60} autoComplete="given-name" className="field font-sans" />
            </Field>
            <div className="sm:col-span-2">
              <span id="earn" className="text-sm">How you earn</span>
              <div role="radiogroup" aria-labelledby="earn" className="mt-2 grid grid-cols-3 border border-line">
                {(Object.keys(EMPLOYMENT_LABEL) as Employment[]).map((value) => (
                  <button key={value} type="button" role="radio" aria-checked={employment === value}
                    onClick={() => setEmployment(value)}
                    className={`h-11 border-r border-line text-sm last:border-r-0 transition-colors duration-150 ${
                      employment === value ? "bg-acc-deep text-fg" : "text-mute hover:text-fg"
                    }`}>
                    {EMPLOYMENT_LABEL[value]}
                  </button>
                ))}
              </div>
            </div>
            <button type="submit" className="btn btn-primary h-12 sm:col-span-2">
              {busy ? `Checking, ${elapsed.toFixed(1)} s` : "Check my eligibility"}
            </button>
          </fieldset>
          {error && (
            <p id="check-error" role="alert" className="flex items-start gap-2 border-t border-line px-4 py-3 text-sm text-coral">
              <WarningCircle size={18} className="mt-0.5 shrink-0" aria-hidden /> {error}
            </p>
          )}
        </form>
      </section>

      <aside aria-label="What happens when you check" className="lg:pt-24">
        <h2 className="text-lg">What happens when you press check</h2>
        <ol className="mt-6 grid border-l border-line">
          {STEPS.map((step) => {
            const done = ORDER.indexOf(stage) > ORDER.indexOf(step.key) || stage === "matched";
            const active = stage === step.key && !done;
            return (
              <li key={step.key} className={`relative py-4 pl-6 ${done || active ? "" : "opacity-60"}`}>
                <span aria-hidden className={`absolute top-[22px] -left-px h-px w-3 ${done ? "bg-acc" : active ? "bg-fg" : "bg-line-hi"}`} />
                <p className="flex items-center gap-2 font-medium">
                  {step.title}
                  {done && <CheckCircle size={16} weight="fill" className="text-acc" aria-label="done" />}
                  {active && <span className="label text-fg">in progress</span>}
                </p>
                <p className="mt-1 text-sm text-mute">{step.detail}</p>
              </li>
            );
          })}
        </ol>
        <p className="mt-6 text-sm text-mute">Usually about ten seconds end to end.</p>
      </aside>
    </div>
  );
}

/** Poll GET /me until Workflow B has written the matches. */
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

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-2">
      <span className="text-sm">{label}</span>
      {children}
      <span className="text-xs text-mute">{hint}</span>
    </label>
  );
}
