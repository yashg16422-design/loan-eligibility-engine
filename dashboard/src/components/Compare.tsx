import { ArrowUpRight, CheckSquare, X } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import type { Match } from "../api/types";
import { loanCost } from "../lib/finance";
import { rupees, rupeesShort } from "../lib/format";
import { CHANNEL_LABEL, checklist } from "../lib/offers";
import { Rate, TierBadge } from "./OfferRow";

export function Compare({ picks, onRemove }: { picks: Match[]; onRemove: (id: string) => void }) {
  const ceiling = Math.min(...picks.map((p) => p.loan_amount_max ?? 2_500_000), 2_500_000);
  const [amount, setAmount] = useState(Math.min(500_000, ceiling));
  const [months, setMonths] = useState(36);

  const rows = useMemo(
    () =>
      picks.map((m) => ({
        m,
        // The advertised starting rate: what you get with a strong profile. Real offers can be higher.
        cost: m.interest_rate_min == null ? null : loanCost(amount, m.interest_rate_min, months),
        fits: (m.loan_amount_max == null || amount <= m.loan_amount_max) && (m.tenure_months_max == null || months <= m.tenure_months_max),
      })),
    [picks, amount, months],
  );
  const priced = rows.filter((r) => r.cost).sort((a, b) => a.cost!.totalInterest - b.cost!.totalInterest);
  const saving = priced.length > 1 ? priced[priced.length - 1].cost!.totalInterest - priced[0].cost!.totalInterest : 0;
  const docs = checklist(picks);

  return (
    <section id="compare" aria-labelledby="compare-title" className="scroll-mt-20">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <h2 id="compare-title" className="text-xl font-semibold">Compare your top {picks.length}</h2>
          <p className="mt-1 text-sm text-mute">At each lender's advertised starting rate. Your actual rate is set by the lender.</p>
        </div>
        <div className="grid w-full gap-4 sm:w-auto sm:grid-cols-2 sm:gap-8">
          <Range label="Loan amount" display={rupeesShort(amount)} value={amount} min={50_000} max={Math.max(ceiling, 100_000)}
            step={10_000} onChange={setAmount} />
          <Range label="Tenure" display={`${months} months`} value={months} min={6} max={84} step={6} onChange={setMonths} />
        </div>
      </div>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <caption className="sr-only">Side-by-side comparison of your selected offers</caption>
          <thead>
            <tr className="text-left">
              <th scope="col" className="w-44 py-3 font-normal text-mute"><span className="sr-only">Measure</span></th>
              {rows.map(({ m }) => (
                <th key={m.product_id} scope="col" className="py-3 pr-4 align-top font-normal">
                  <div className="flex items-start justify-between gap-2">
                    <span>
                      <span className="block font-medium text-fg">{m.lender}</span>
                      <span className="text-mute">{CHANNEL_LABEL[m.channel]}</span>
                    </span>
                    <button type="button" onClick={() => onRemove(m.product_id)} aria-label={`Remove ${m.lender} from comparison`}
                      className="grid size-7 place-items-center text-mute hover:bg-panel-2 hover:text-fg">
                      <X size={14} />
                    </button>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="[&_td]:border-t [&_td]:border-line [&_th]:border-t [&_th]:border-line">
            <Row label="Status">{rows.map(({ m }) => <TierBadge key={m.product_id} tier={m.tier} />)}</Row>
            <Row label="Interest rate">{rows.map(({ m }) => <Rate key={m.product_id} min={m.interest_rate_min} max={m.interest_rate_max} />)}</Row>
            <Row label="Monthly EMI" num strong>
              {rows.map(({ m, cost, fits }) => (cost ? <span key={m.product_id}>{rupees(cost.emi)}{!fits && <Note>outside limits</Note>}</span> : "Rate on request"))}
            </Row>
            <Row label="Total interest" num>{rows.map(({ cost }) => (cost ? rupees(cost.totalInterest) : "-"))}</Row>
            <Row label="Largest loan" num>{rows.map(({ m }) => rupeesShort(m.loan_amount_max))}</Row>
            <Row label="Longest tenure" num>{rows.map(({ m }) => (m.tenure_months_max ? `${m.tenure_months_max} months` : "-"))}</Row>
            <Row label="Fit score" num>{rows.map(({ m }) => m.fit_score)}</Row>
            <Row label="">
              {rows.map(({ m }) =>
                m.product_url ? (
                  <a key={m.product_id} href={m.product_url} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 underline decoration-line-hi hover:decoration-fg">
                    Apply on {CHANNEL_LABEL[m.channel]} <ArrowUpRight size={14} aria-hidden />
                  </a>
                ) : "-",
              )}
            </Row>
          </tbody>
        </table>
      </div>

      {saving > 0 && (
        <p className="mt-4 text-sm">
          {priced[0].m.lender} costs <span className="num font-medium text-acc">{rupees(saving)}</span> less in interest than{" "}
          {priced[priced.length - 1].m.lender} on this loan.
        </p>
      )}

      {docs.length > 0 && (
        <div className="mt-8">
          <h3 className="font-medium">Before you apply, have these ready</h3>
          <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            {docs.map((d) => (
              <li key={d} className="flex gap-2 text-mute">
                <CheckSquare size={18} className="mt-px shrink-0" aria-hidden />
                {d}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function Row({ label, num, strong, children }: { label: string; num?: boolean; strong?: boolean; children: React.ReactNode[] }) {
  return (
    <tr>
      <th scope="row" className="py-3 pr-4 text-left font-normal text-mute">{label}</th>
      {children.map((c, i) => (
        <td key={i} className={`py-3 pr-4 align-top ${num ? "num" : ""} ${strong ? "text-base font-medium" : ""}`}>{c}</td>
      ))}
    </tr>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <span className="ml-2 font-sans text-xs font-normal text-mute">({children})</span>;
}

function Range({ label, display, value, min, max, step, onChange }: {
  label: string; display: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <label className="grid min-w-[200px] gap-1.5 text-sm">
      <span className="flex justify-between gap-4"><span className="text-mute">{label}</span><span className="num">{display}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} aria-valuetext={display} className="accent-[var(--color-acc)]" />
    </label>
  );
}
