import { BellRinging, CircleNotch, Scales, WarningCircle } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import type { Me, Profile } from "../api/types";
import { Compare } from "../components/Compare";
import { OfferRow } from "../components/OfferRow";
import { WhatIf } from "../components/WhatIf";
import { EMPLOYMENT_LABEL, count, rupees, rupeesShort } from "../lib/format";
import { groupByLender, sortOffers, type SortKey } from "../lib/offers";
import { toggleCompare, toggleHidden, toggleSaved, useDashboard } from "../lib/useDashboard";
import { Link } from "../router";

type Filter = "all" | "eligible" | "conditional" | "saved";

export function Dashboard() {
  const { load, prefs, update, saveError, retry } = useDashboard();
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<SortKey>("fit");
  const [showHidden, setShowHidden] = useState(false);

  const ready = load.state === "ready" ? load : null;
  const offers = useMemo(() => (ready ? groupByLender(ready.matches) : []), [ready]);

  if (load.state === "loading") return <Skeleton />;
  if (load.state === "signed-out") return <SignedOut />;
  if (load.state === "queued") return <Queued />;
  if (load.state === "error") return <ErrorState message={load.message} onRetry={retry} />;

  const { me, matches, catalog } = load;
  const profile: Profile = { monthly_income: me.monthly_income, credit_score: me.credit_score, age: me.age, employment_status: me.employment_status };
  const hiddenSet = new Set(prefs.hidden);
  const counts = {
    all: offers.filter((o) => !hiddenSet.has(o.best.product_id)).length,
    eligible: offers.filter((o) => o.best.tier === "eligible" && !hiddenSet.has(o.best.product_id)).length,
    conditional: offers.filter((o) => o.best.tier === "conditional" && !hiddenSet.has(o.best.product_id)).length,
    saved: offers.filter((o) => prefs.shortlist.includes(o.best.product_id)).length,
  };
  const visible = sortOffers(offers, sort).filter((o) => {
    const id = o.best.product_id;
    if (hiddenSet.has(id) && !showHidden) return false;
    if (filter === "saved") return prefs.shortlist.includes(id);
    if (filter === "all") return true;
    return o.best.tier === filter;
  });
  const picks = prefs.top3.map((id) => matches.find((m) => m.product_id === id)).filter((m) => m != null);

  return (
    <div className="mx-auto max-w-[1240px] px-4 pt-10 pb-16 sm:px-6">
      <Summary me={me} lendersOutright={counts.eligible} />

      {saveError && (
        <p role="status" className="mt-6 flex items-center gap-2 text-sm text-danger">
          <WarningCircle size={16} aria-hidden /> {saveError}
        </p>
      )}

      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-12">
        <section aria-labelledby="offers-title" className="@container min-w-0">
          <h2 id="offers-title" className="sr-only">Your offers</h2>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
            <div role="tablist" aria-label="Filter offers" className="flex flex-wrap gap-1">
              {([
                ["all", "All"], ["eligible", "Eligible"], ["conditional", "May qualify"], ["saved", "Saved"],
              ] as [Filter, string][]).map(([key, label]) => (
                <button key={key} role="tab" type="button" aria-selected={filter === key} onClick={() => setFilter(key)}
                  className={`rounded-[var(--radius-ctl)] px-3 py-1.5 text-sm transition-colors duration-150 ${
                    filter === key ? "bg-raise text-text" : "text-muted hover:text-text"
                  }`}>
                  {label} <span className="num text-muted">{counts[key]}</span>
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm text-muted">
              Sort by
              <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}
                className="h-8 rounded-[var(--radius-ctl)] border border-line-strong bg-panel px-2 text-text focus:border-marigold focus:outline-none">
                <option value="fit">Best fit</option>
                <option value="rate">Lowest rate</option>
                <option value="amount">Largest loan</option>
              </select>
            </label>
          </div>

          <div className="hidden grid-cols-[minmax(0,1fr)_170px_140px_112px_116px] gap-x-4 px-1 pt-3 text-xs text-muted @3xl:grid">
            <span className="pl-7">Lender</span><span className="text-right">Interest rate</span>
            <span className="text-right">Loan size</span><span>Status</span><span />
          </div>

          {visible.length ? (
            <ul>
              {visible.map((o) => {
                const id = o.best.product_id;
                return (
                  <OfferRow key={o.lender_key} offer={o} profile={profile}
                    saved={prefs.shortlist.includes(id)} comparing={prefs.top3.includes(id)} compareFull={prefs.top3.length >= 3}
                    hidden={hiddenSet.has(id)}
                    onSave={() => update(toggleSaved(id))} onCompare={() => update(toggleCompare(id))} onHide={() => update(toggleHidden(id))} />
                );
              })}
            </ul>
          ) : (
            <p className="py-12 text-sm text-muted">
              {filter === "saved" ? "Save an offer with the bookmark to keep it here." : "No offers in this view. Try All."}
            </p>
          )}

          {prefs.hidden.length > 0 && (
            <button type="button" onClick={() => setShowHidden((s) => !s)} className="mt-4 text-sm text-muted underline decoration-line-strong hover:text-text">
              {showHidden ? "Hide the offers you dismissed" : `Show ${count(prefs.hidden.length, "dismissed offer")}`}
            </button>
          )}
        </section>

        <aside className="grid content-start gap-6 lg:sticky lg:top-20 lg:self-start">
          <WhatIf catalog={catalog} profile={profile} />
          <CompareTray picks={picks.length} />
          <AlertsToggle on={prefs.alerts} onChange={(alerts) => update((p) => ({ ...p, alerts }))} />
        </aside>
      </div>

      {picks.length > 0 && (
        <div className="mt-16 border-t border-line pt-10">
          <Compare picks={picks} onRemove={(id) => update(toggleCompare(id))} />
        </div>
      )}
    </div>
  );
}

function Summary({ me, lendersOutright }: { me: Me; lendersOutright: number }) {
  const greeting = me.name?.split(/\s+/)[0];
  const possible = me.lenders - lendersOutright;
  return (
    <section aria-labelledby="summary-title" className="max-w-[760px]">
      <h1 id="summary-title" className="text-2xl font-semibold leading-snug sm:text-3xl">
        {greeting ? `${greeting}, you` : "You"} qualify outright with {count(lendersOutright, "lender")}
        {possible > 0 && `, and may qualify with ${possible} more`}.
      </h1>
      <p className="mt-3 text-muted">
        Based on <span className="num whitespace-nowrap text-text">{rupees(me.monthly_income)}</span> a month, a credit score of{" "}
        <span className="num text-text">{me.credit_score}</span>, {EMPLOYMENT_LABEL[me.employment_status].toLowerCase()}, age{" "}
        <span className="num text-text">{me.age}</span>.
        {me.best_rate != null && <> Rates start at <span className="num text-text">{me.best_rate}%</span>, loans up to <span className="num whitespace-nowrap text-text">{rupeesShort(me.max_amount)}</span>.</>}{" "}
        <Link to="check" className="text-text underline decoration-line-strong hover:decoration-marigold">Run a new check</Link>
      </p>
    </section>
  );
}

function CompareTray({ picks }: { picks: number }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-[var(--radius-ctl)] border border-line p-4 text-sm">
      <span className="flex items-center gap-2">
        <Scales size={18} className="text-muted" aria-hidden />
        {picks ? `${picks} of 3 picked to compare` : "Pick up to 3 offers to compare"}
      </span>
      {picks > 0 && <a href="#compare" className="text-marigold underline decoration-marigold/40 hover:decoration-marigold">Compare</a>}
    </div>
  );
}

function AlertsToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-[var(--radius-ctl)] border border-line p-4 text-sm">
      <span className="flex gap-2">
        <BellRinging size={18} className="mt-px shrink-0 text-muted" aria-hidden />
        <span>
          <span className="block">Tell me when a new lender matches</span>
          <span className="text-muted">Lender sites are re-read every morning; you are re-matched automatically.</span>
        </span>
      </span>
      <input type="checkbox" role="switch" checked={on} onChange={(e) => onChange(e.target.checked)} className="mt-1 size-4 accent-[var(--color-marigold)]" />
    </label>
  );
}

function Skeleton() {
  return (
    <div className="mx-auto max-w-[1240px] animate-pulse px-4 pt-10 sm:px-6" aria-busy="true" aria-label="Loading your matches">
      <div className="h-9 w-2/3 rounded bg-panel" />
      <div className="mt-4 h-5 w-1/2 rounded bg-panel" />
      <div className="mt-12 grid gap-10 lg:grid-cols-[1fr_340px]">
        <div className="grid gap-3">{Array.from({ length: 6 }, (_, i) => <div key={i} className="h-16 rounded bg-panel" />)}</div>
        <div className="h-96 rounded bg-panel" />
      </div>
    </div>
  );
}

function SignedOut() {
  return (
    <div className="mx-auto max-w-[560px] px-4 pt-24 pb-24 sm:px-6">
      <h1 className="text-2xl font-semibold">Your matches open from a check or an email link.</h1>
      <p className="mt-3 text-muted">There's no account and no password. Run a check, or open the "View my matches" link in your email.</p>
      <Link to="check" className="mt-8 inline-flex h-11 items-center rounded-[var(--radius-ctl)] bg-marigold px-5 font-medium text-marigold-ink no-underline">
        Check my eligibility
      </Link>
    </div>
  );
}

function Queued() {
  return (
    <div className="mx-auto flex max-w-[560px] items-center gap-3 px-4 pt-24 sm:px-6" role="status">
      <CircleNotch size={22} className="animate-spin text-marigold" aria-hidden />
      <p>Matching your profile against every lender. This takes about ten seconds.</p>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mx-auto max-w-[560px] px-4 pt-24 sm:px-6" role="alert">
      <h1 className="text-xl font-semibold">Your matches didn't load.</h1>
      <p className="mt-2 text-muted">{message}</p>
      <button type="button" onClick={onRetry} className="mt-6 h-10 rounded-[var(--radius-ctl)] border border-line-strong px-4 text-sm hover:bg-raise">
        Try again
      </button>
    </div>
  );
}
