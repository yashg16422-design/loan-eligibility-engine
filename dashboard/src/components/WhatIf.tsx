import { ArrowCounterClockwise, Lightbulb } from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";
import type { CatalogProduct, Employment, Profile } from "../api/types";
import { decide, nextUnlock } from "../lib/eligibility";
import { EMPLOYMENT_LABEL, rupees } from "../lib/format";

interface Reach {
  outright: Set<string>; // lenders with at least one "eligible" product
  possible: Set<string>; // lenders with any product in reach
  names: Map<string, string>;
}

function reach(catalog: CatalogProduct[], u: Profile): Reach {
  const r: Reach = { outright: new Set(), possible: new Set(), names: new Map() };
  for (const p of catalog) {
    r.names.set(p.lender_key, p.lender);
    const tier = decide(p, u);
    if (tier !== "not_eligible") r.possible.add(p.lender_key);
    if (tier === "eligible") r.outright.add(p.lender_key);
  }
  return r;
}

export function WhatIf({ catalog, profile }: { catalog: CatalogProduct[]; profile: Profile }) {
  const [sim, setSim] = useState<Profile>(profile);
  const reduce = useReducedMotion();
  const today = useMemo(() => reach(catalog, profile), [catalog, profile]);
  const now = useMemo(() => reach(catalog, sim), [catalog, sim]);
  const unlock = useMemo(() => nextUnlock(catalog, sim), [catalog, sim]);
  const changed = JSON.stringify(sim) !== JSON.stringify(profile);

  const gained = [...now.possible].filter((k) => !today.possible.has(k));
  const lost = [...today.possible].filter((k) => !now.possible.has(k));
  const set = <K extends keyof Profile>(key: K, value: Profile[K]) => setSim((s) => ({ ...s, [key]: value }));

  return (
    <section aria-labelledby="whatif-title" className="rounded-[var(--radius-ctl)] border border-line bg-panel p-5">
      <div className="flex items-center justify-between">
        <h2 id="whatif-title" className="font-medium">What if</h2>
        {changed && (
          <button type="button" onClick={() => setSim(profile)}
            className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-text">
            <ArrowCounterClockwise size={14} aria-hidden />
            Back to my profile
          </button>
        )}
      </div>

      <div className="mt-5 grid gap-5">
        <Slider label="Monthly income" value={sim.monthly_income} display={rupees(sim.monthly_income)}
          min={10000} max={300000} step={1000} onChange={(v) => set("monthly_income", v)} />
        <Slider label="Credit score" value={sim.credit_score} display={String(sim.credit_score)}
          min={300} max={900} step={5} onChange={(v) => set("credit_score", v)} />
        <Slider label="Age" value={sim.age} display={`${sim.age}`} min={18} max={70} step={1}
          onChange={(v) => set("age", v)} />
        <label className="grid gap-2 text-sm">
          <span className="text-muted">How you earn</span>
          <select value={sim.employment_status} onChange={(e) => set("employment_status", e.target.value as Employment)}
            className="h-9 rounded-[var(--radius-ctl)] border border-line-strong bg-ink px-2 text-text focus:border-marigold focus:outline-none">
            {(Object.keys(EMPLOYMENT_LABEL) as Employment[]).map((k) => (
              <option key={k} value={k}>{EMPLOYMENT_LABEL[k]}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-6 border-t border-line pt-5" aria-live="polite">
        <p className="text-sm">
          <span className="num text-lg font-medium">{now.possible.size}</span>
          <span className="text-muted"> lenders in reach, </span>
          <span className="num font-medium">{now.outright.size}</span>
          <span className="text-muted"> outright</span>
          {changed && (
            <span className="text-muted">
              {today.possible.size === now.possible.size && today.outright.size === now.outright.size
                ? ". Same as today."
                : `. Today: ${today.possible.size} and ${today.outright.size}.`}
            </span>
          )}
        </p>

        <ul className="mt-3 flex flex-wrap gap-1.5">
          <AnimatePresence initial={false}>
            {gained.map((k) => (
              <motion.li key={`+${k}`} layout={!reduce}
                initial={reduce ? false : { opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}
                exit={reduce ? undefined : { opacity: 0, scale: 0.9 }} transition={{ duration: 0.18 }}
                className="rounded-[var(--radius-ctl)] bg-marigold/15 px-2 py-1 text-xs text-marigold">
                + {now.names.get(k)}
              </motion.li>
            ))}
            {lost.map((k) => (
              <motion.li key={`-${k}`} layout={!reduce}
                initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={reduce ? undefined : { opacity: 0 }}
                className="rounded-[var(--radius-ctl)] border border-line px-2 py-1 text-xs text-muted line-through">
                {today.names.get(k)}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>

        {unlock && (
          <p className="mt-4 flex gap-2 text-sm text-muted">
            <Lightbulb size={16} className="mt-0.5 shrink-0 text-marigold" aria-hidden />
            <span>
              With {unlock.field === "credit_score" ? `a credit score of ${unlock.to}` : `an income of ${rupees(unlock.to)}`},{" "}
              <span className="text-text">{unlock.lenders.slice(0, 3).join(", ")}</span>
              {unlock.lenders.length > 3 && ` and ${unlock.lenders.length - 3} more`}
              {unlock.lenders.length === 1 ? " comes" : " come"} into reach.
            </span>
          </p>
        )}
        <p className="mt-4 text-xs text-muted">
          Uses the same rules as the matching engine. Your saved matches change only when you run a new check.
        </p>
      </div>
    </section>
  );
}

function Slider({ label, value, display, min, max, step, onChange }: {
  label: string; value: number; display: string; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <label className="grid gap-2 text-sm">
      <span className="flex justify-between">
        <span className="text-muted">{label}</span>
        <span className="num">{display}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} aria-label={label} aria-valuetext={display} className="w-full" />
    </label>
  );
}
