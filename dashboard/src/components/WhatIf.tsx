import { ArrowCounterClockwise } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import type { CatalogProduct, Employment, Profile } from "../api/types";
import { decide, nextUnlock } from "../lib/eligibility";
import { EMPLOYMENT_LABEL, rupees } from "../lib/format";
import { Select } from "../ui/Select";

interface Reach {
  outright: Set<string>;
  possible: Set<string>;
  names: Map<string, string>;
}

export function reach(catalog: CatalogProduct[], u: Profile): Reach {
  const r: Reach = { outright: new Set(), possible: new Set(), names: new Map() };
  for (const p of catalog) {
    r.names.set(p.lender_key, p.lender);
    const tier = decide(p, u);
    if (tier !== "not_eligible") r.possible.add(p.lender_key);
    if (tier === "eligible") r.outright.add(p.lender_key);
  }
  return r;
}

const EMPLOYMENT_OPTIONS = (Object.keys(EMPLOYMENT_LABEL) as Employment[]).map((value) => ({ value, label: EMPLOYMENT_LABEL[value] }));

export function WhatIf({ catalog, profile }: { catalog: CatalogProduct[]; profile: Profile }) {
  const [sim, setSim] = useState<Profile>(profile);
  const today = useMemo(() => reach(catalog, profile), [catalog, profile]);
  const now = useMemo(() => reach(catalog, sim), [catalog, sim]);
  const unlock = useMemo(() => nextUnlock(catalog, sim), [catalog, sim]);
  const changed = JSON.stringify(sim) !== JSON.stringify(profile);
  const gained = [...now.possible].filter((k) => !today.possible.has(k)).map((k) => now.names.get(k)!);
  const lost = [...today.possible].filter((k) => !now.possible.has(k)).map((k) => today.names.get(k)!);
  const set = <K extends keyof Profile>(key: K, value: Profile[K]) => setSim((s) => ({ ...s, [key]: value }));

  return (
    <section aria-labelledby="whatif-title" className="box tick p-7" style={{ ["--tick" as string]: "var(--color-peri)" }}>
      <div className="flex items-center justify-between">
        <h2 id="whatif-title" className="text-lg">What if</h2>
        {changed && (
          <button type="button" onClick={() => setSim(profile)} className="inline-flex items-center gap-1.5 text-sm text-mute hover:text-fg">
            <ArrowCounterClockwise size={14} aria-hidden /> Reset
          </button>
        )}
      </div>
      <p className="mt-1 text-sm text-mute">Same rules as the matching engine.</p>
      <div className="mt-5 grid gap-5">
        <Slider label="Monthly income" value={sim.monthly_income} display={rupees(sim.monthly_income)} min={10000} max={300000} step={1000}
          onChange={(v) => set("monthly_income", v)} />
        <Slider label="Credit score" value={sim.credit_score} display={String(sim.credit_score)} min={300} max={900} step={5}
          onChange={(v) => set("credit_score", v)} />
        <Slider label="Age" value={sim.age} display={String(sim.age)} min={18} max={70} step={1} onChange={(v) => set("age", v)} />
        <Select label="How you earn" value={sim.employment_status} options={EMPLOYMENT_OPTIONS} onChange={(v) => set("employment_status", v)} />
      </div>
      <div className="mt-6 border-t border-line pt-5 text-sm" aria-live="polite">
        <p>
          <span className="num text-lg">{now.possible.size}</span> <span className="text-mute">lenders in reach,</span>{" "}
          <span className="num">{now.outright.size}</span> <span className="text-mute">outright.</span>
          {changed && (
            <span className="text-mute">
              {" "}{gained.length || lost.length ? `Today: ${today.possible.size} and ${today.outright.size}.` : "Same as today."}
            </span>
          )}
        </p>
        {gained.length > 0 && <p className="mt-2 text-acc">Comes into reach: {gained.join(", ")}</p>}
        {lost.length > 0 && <p className="mt-2 text-coral">Falls out of reach: {lost.join(", ")}</p>}
        {unlock && (
          <p className="mt-3 text-mute">
            With {unlock.field === "credit_score" ? `a credit score of ${unlock.to}` : `an income of ${rupees(unlock.to)}`},{" "}
            <span className="text-fg">{unlock.lenders.slice(0, 3).join(", ")}</span>
            {unlock.lenders.length > 3 && ` and ${unlock.lenders.length - 3} more`}
            {unlock.lenders.length === 1 ? " comes" : " come"} into reach.
          </p>
        )}
      </div>
    </section>
  );
}

function Slider({ label, value, display, min, max, step, onChange }: {
  label: string; value: number; display: string; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <label className="grid gap-2 text-sm">
      <span className="flex justify-between"><span>{label}</span><span className="num">{display}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} aria-valuetext={display}
        onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-[var(--color-acc)]" />
    </label>
  );
}
