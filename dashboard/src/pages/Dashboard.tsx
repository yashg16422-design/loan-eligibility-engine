import { BookmarkSimple, Lightbulb, Minus, Plus, Scales, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, session } from "../api/client";
import type { CatalogProduct, Me, Profile } from "../api/types";
import { Compare } from "../components/Compare";
import { Actions, OfferRow, Rate, TierBadge, type RowActions } from "../components/OfferRow";
import { WhatIf } from "../components/WhatIf";
import { decide, whyNot } from "../lib/eligibility";
import { EMPLOYMENT_LABEL, count, rupees, rupeesShort } from "../lib/format";
import { CHANNEL_PHRASE, groupByLender, type LenderOffer } from "../lib/offers";
import { tips } from "../lib/tips";
import { pendingSave, useSignedIn } from "../lib/useAccount";
import { toggleCompare, toggleHidden, toggleSaved, useDashboard } from "../lib/useDashboard";
import { Link, navigate } from "../router";
import { ConfirmDelete } from "../ui/Confirm";

const TOP = 5;

export function Dashboard() {
  const { load, prefs, update, saveError, retry } = useDashboard();
  const [showHidden, setShowHidden] = useState(false);
  const ready = load.state === "ready" ? load : null;
  const offers = useMemo(() => (ready ? groupByLender(ready.matches) : []), [ready]);

  if (load.state === "loading") return <Skeleton />;
  if (load.state === "signed-out") return <NoResults />;
  if (load.state === "queued") return <Notice>Matching your profile against every lender. This takes about ten seconds.</Notice>;
  if (load.state === "error") return <ErrorState message={load.message} onRetry={retry} />;

  const { me, matches, catalog } = load;
  const profile: Profile = { monthly_income: me.monthly_income, credit_score: me.credit_score, age: me.age, employment_status: me.employment_status };
  const hidden = new Set(prefs.hidden);
  const visible = offers.filter((o) => showHidden || !hidden.has(o.best.product_id));
  const top = visible.slice(0, TOP);
  const rest = visible.slice(TOP);
  const eligible = rest.filter((o) => o.best.tier === "eligible");
  const conditional = rest.filter((o) => o.best.tier === "conditional");
  const actions = (o: LenderOffer): RowActions => {
    const id = o.best.product_id;
    return {
      saved: prefs.shortlist.includes(id), comparing: prefs.top3.includes(id), compareFull: prefs.top3.length >= 3, hidden: hidden.has(id),
      onSave: () => update(toggleSaved(id)), onCompare: () => update(toggleCompare(id)), onHide: () => update(toggleHidden(id)),
    };
  };
  const picks = prefs.top3.map((id) => matches.find((m) => m.product_id === id)).filter((m) => m != null);
  const outright = offers.filter((o) => o.best.tier === "eligible").length;

  return (
    <div className="mx-auto max-w-[1480px] px-5 pt-14 pb-10 lg:pt-20 sm:px-10 xl:px-16">
      <Summary me={me} outright={outright} possible={offers.length - outright} />
      <SaveBanner />
      {saveError && <p role="status" className="mt-4 flex items-center gap-2 text-sm text-coral"><WarningCircle size={16} aria-hidden /> {saveError}</p>}

      <div className="mt-14 grid gap-14 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="grid min-w-0 content-start gap-20">
          <section aria-labelledby="top-title">
            <SectionHead id="top-title" title={`Your top ${top.length}`} note="One offer per lender, on the platform that fits you best" />
            <ol className="mt-8 grid gap-5 md:grid-cols-2">
              {top.map((o, i) => <TopPick key={o.lender_key} rank={i + 1} offer={o} actions={actions(o)} />)}
            </ol>
          </section>

          <OfferSection id="eligible" title="Also eligible" note="You meet every rule these lenders publish" offers={eligible} profile={profile} actions={actions} defaultOpen />
          <OfferSection id="maybe" title="May qualify" note="You pass the checkable rules; the lender asks for more (or publishes no criteria)" offers={conditional} profile={profile} actions={actions} />
          <NotEligible catalog={catalog} profile={profile} reachable={new Set(offers.map((o) => o.lender_key))} />

          <section aria-labelledby="tips-title">
            <SectionHead id="tips-title" title="Quick tips" />
            <ul className="mt-8 grid gap-px border border-line bg-line">
              {tips(offers, matches, catalog, profile).map((t) => (
                <li key={t} className="flex gap-3 bg-panel p-6 text-sm">
                  <Lightbulb size={18} className="mt-0.5 shrink-0 text-amber" aria-hidden /> {t}
                </li>
              ))}
            </ul>
            {prefs.hidden.length > 0 && (
              <button type="button" onClick={() => setShowHidden((s) => !s)} className="mt-4 text-sm text-mute underline">
                {showHidden ? "Hide the offers you dismissed" : `Show ${count(prefs.hidden.length, "dismissed offer")}`}
              </button>
            )}
          </section>
        </div>

        <aside className="grid content-start gap-5 lg:sticky lg:top-20 lg:self-start">
          <WhatIf catalog={catalog} profile={profile} />
          <div className="box flex items-center justify-between gap-4 p-6 text-sm">
            <span className="flex items-center gap-2"><Scales size={18} className="text-mute" aria-hidden />
              {picks.length ? `${picks.length} of 3 picked to compare` : "Pick up to 3 offers to compare"}</span>
            {picks.length > 0 && <a href="#compare" className="text-acc underline">Compare</a>}
          </div>
        </aside>
      </div>

      {picks.length > 0 && (
        <div className="mt-24 border-t border-line pt-10">
          <Compare picks={picks} onRemove={(id) => update(toggleCompare(id))} />
        </div>
      )}
      {/* Outside the sticky aside: a tall sidebar would push this below a short screen for good. */}
      {me.source === "instant_check" && <StartOver />}
    </div>
  );
}

function Summary({ me, outright, possible }: { me: Me; outright: number; possible: number }) {
  const first = me.name?.split(/\s+/)[0];
  return (
    <section aria-labelledby="summary-title" className="max-w-[820px]">
      <h1 id="summary-title" className="text-3xl leading-tight sm:text-4xl">
        {first ? `${first}, you` : "You"} qualify outright with {count(outright, "lender")}
        {possible > 0 && `, and may qualify with ${possible} more`}.
      </h1>
      <p className="mt-3 text-mute">
        For <span className="num whitespace-nowrap text-fg">{rupees(me.monthly_income)}</span> a month, a credit score of{" "}
        <span className="num text-fg">{me.credit_score}</span>, {EMPLOYMENT_LABEL[me.employment_status].toLowerCase()}, age{" "}
        <span className="num text-fg">{me.age}</span>.
        {me.best_rate != null && <> Rates from <span className="num text-fg">{me.best_rate}%</span>, loans up to <span className="num whitespace-nowrap text-fg">{rupeesShort(me.max_amount)}</span>.</>}{" "}
        <Link to="check" className="text-fg underline decoration-line-hi hover:decoration-fg">Run a new check</Link>
      </p>
    </section>
  );
}

/** Save prompt: anonymous until here; signing in keeps these results and refreshes them daily. */
function SaveBanner() {
  const email = useSignedIn();
  const [state, setState] = useState<{ phase: "idle" | "saving" | "done" | "error"; message?: string }>({ phase: "idle" });

  const save = async () => {
    const token = session.get();
    if (!token) return;
    setState({ phase: "saving" });
    try {
      const r = await api.saveProfile(token);
      setState({ phase: r.outcome === "taken" ? "error" : "done", message: r.message });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        pendingSave.set();
        navigate("account");
        return;
      }
      setState({ phase: "error", message: err instanceof Error ? err.message : "Could not save. Try again." });
    }
  };
  useEffect(() => {
    if (email && pendingSave.take()) void save(); // finishing a save that started before sign-in
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email]);

  if (state.phase === "done") {
    return (
      <p className="box tick mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 p-6 text-sm">
        <BookmarkSimple size={18} weight="fill" className="text-acc" aria-hidden /> {state.message} Your top picks are refreshed every
        morning after the 06:00 lender crawl. <Link to="account" className="underline">Account</Link>
      </p>
    );
  }
  return (
    <div className="box tick mt-6 flex flex-wrap items-center justify-between gap-4 p-6">
      <p className="text-sm">
        <span className="font-medium">Keep these results.</span>{" "}
        <span className="text-mute">Save them to an account and your top picks are ready every morning, after lenders' sites are re-read at 06:00.</span>
        {state.phase === "error" && <span className="mt-1 block text-coral">{state.message}</span>}
      </p>
      <button type="button" onClick={() => (email ? void save() : (pendingSave.set(), navigate("account")))} disabled={state.phase === "saving"} className="btn btn-primary">
        <BookmarkSimple size={16} aria-hidden /> {state.phase === "saving" ? "Saving" : email ? "Save to my account" : "Save my results"}
      </button>
    </div>
  );
}

function TopPick({ rank, offer, actions }: { rank: number; offer: LenderOffer; actions: RowActions }) {
  const m = offer.best;
  return (
    <li className={`box tick grid gap-4 p-8 ${rank === 1 ? "md:col-span-2" : ""}`} style={{ ["--tick" as string]: m.tier === "eligible" ? "var(--color-acc)" : "var(--color-amber)" }}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="label">{rank === 1 ? "Best pick" : `Pick ${rank}`}</p>
          <h3 className={`mt-1 ${rank === 1 ? "text-2xl" : "text-lg"}`}>{offer.lender}</h3>
          <p className="text-sm text-mute">on {CHANNEL_PHRASE[m.channel]}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <TierBadge tier={m.tier} />
          <span className="text-sm text-mute">fit <span className="num text-fg">{m.fit_score}</span></span>
        </div>
      </div>
      <p className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <Rate min={m.interest_rate_min} max={m.interest_rate_max} />
        <span className="text-mute">{m.loan_amount_max ? <>up to <span className="num text-fg">{rupeesShort(m.loan_amount_max)}</span></> : "amount not stated"}</span>
      </p>
      {m.requirements && <p className="text-sm text-mute">Also needs: {m.requirements}</p>}
      <div className="-ml-2 flex items-center justify-between">
        <Actions actions={actions} />
        {m.product_url && /^https?:\/\//.test(m.product_url) && (
          <a href={m.product_url} target="_blank" rel="noopener noreferrer" className="text-sm underline decoration-line-hi hover:decoration-fg">View offer</a>
        )}
      </div>
    </li>
  );
}

function OfferSection({ id, title, note, offers, profile, actions, defaultOpen = false }: {
  id: string; title: string; note: string; offers: LenderOffer[]; profile: Profile; actions: (o: LenderOffer) => RowActions; defaultOpen?: boolean;
}) {
  if (!offers.length) return null;
  return (
    <Collapsible id={id} title={title} count={offers.length} note={note} defaultOpen={defaultOpen}>
      <ul className="@container border border-line bg-panel">
        {offers.map((o) => <OfferRow key={o.lender_key} offer={o} profile={profile} actions={actions(o)} />)}
      </ul>
    </Collapsible>
  );
}

/** A results section whose list opens on demand: the count and the meaning are always visible. */
function Collapsible({ id, title, count, note, defaultOpen, children }: {
  id: string; title: string; count: number; note: string; defaultOpen: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section aria-labelledby={`${id}-title`}>
      <button type="button" aria-expanded={open} aria-controls={`${id}-panel`} onClick={() => setOpen((o) => !o)}
        className="group flex w-full items-end justify-between gap-6 border-b border-line pb-5 text-left">
        <span>
          <h2 id={`${id}-title`} className="text-2xl">{title} <span className="num text-mute">{count}</span></h2>
          <span className="mt-2 block text-sm text-mute">{note}</span>
        </span>
        <span aria-hidden className="grid size-9 shrink-0 place-items-center border border-line-hi text-mute transition-colors duration-150 group-hover:border-fg group-hover:text-fg">
          {open ? <Minus size={14} /> : <Plus size={14} />}
        </span>
      </button>
      <div id={`${id}-panel`} hidden={!open} className="pt-8">{open && children}</div>
    </section>
  );
}

function NotEligible({ catalog, profile, reachable }: { catalog: CatalogProduct[]; profile: Profile; reachable: Set<string> }) {
  const [all, setAll] = useState(false);
  // Lenders with no product in reach, each with the reasons of its closest product.
  const rows = useMemo(() => {
    const by = new Map<string, { lender: string; reasons: string[] }>();
    for (const p of catalog) {
      if (reachable.has(p.lender_key) || decide(p, profile) !== "not_eligible") continue;
      const reasons = whyNot(p, profile);
      const prev = by.get(p.lender_key);
      if (!prev || reasons.length < prev.reasons.length) by.set(p.lender_key, { lender: p.lender, reasons });
    }
    return [...by.values()].sort((a, b) => a.reasons.length - b.reasons.length || a.lender.localeCompare(b.lender));
  }, [catalog, profile, reachable]);
  if (!rows.length) return null;
  const shown = all ? rows : rows.slice(0, 6);
  return (
    <Collapsible id="no" title="Not eligible yet" count={rows.length} note="The exact published rule you miss, so you know what to change" defaultOpen={false}>
      <ul className="grid gap-px border border-line bg-line sm:grid-cols-2">
        {shown.map((r) => (
          <li key={r.lender} className="bg-panel p-6">
            <p className="flex items-center justify-between gap-3"><span className="font-medium">{r.lender}</span><TierBadge tier="not_eligible" /></p>
            <ul className="mt-2 grid gap-0.5 text-sm text-mute">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
          </li>
        ))}
      </ul>
      {rows.length > 6 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-3 text-sm text-mute underline underline-offset-4">
          {all ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
    </Collapsible>
  );
}

function SectionHead({ id, title, note }: { id: string; title: string; note?: string }) {
  return (
    <div>
      <h2 id={id} className="text-2xl">{title}</h2>
      {note && <p className="mt-1 text-sm text-mute">{note}</p>}
    </div>
  );
}

/** Delete this instant check (and its matches) to start again; an account is never touched. */
function StartOver() {
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="mt-24 flex flex-wrap items-center justify-between gap-6 border-t border-line pt-10 text-sm">
      <div>
        <h3 className="font-medium">Start over</h3>
        <p className="mt-1 text-mute">Deletes this check and its matches from our database. Your account, if you have one, stays.</p>
        {error && <p role="alert" className="mt-3 text-coral">{error}</p>}
      </div>
      <div>
        <ConfirmDelete
          small
          label="Delete this check"
          question="Delete this check?"
          onConfirm={async () => {
            try {
              await api.deleteMyCheck();
              session.clear();
              navigate("check");
            } catch (err) {
              setError(err instanceof Error ? err.message : "Nothing was deleted. Try again.");
            }
          }}
        />
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="mx-auto max-w-[1480px] px-5 pt-14 sm:px-10 lg:pt-20 xl:px-16" aria-busy="true" aria-label="Loading your matches">
      <div className="h-10 w-2/3 bg-panel" />
      <div className="mt-4 h-5 w-1/2 bg-panel" />
      <div className="mt-10 grid gap-3 md:grid-cols-2">{Array.from({ length: 4 }, (_, i) => <div key={i} className="h-36 border border-line bg-panel" />)}</div>
    </div>
  );
}

function NoResults() {
  return (
    <div className="mx-auto max-w-[620px] px-5 pt-20 pb-16 sm:px-10 xl:px-16">
      <h1 className="text-3xl">Your matches open from a check, an email link or your account.</h1>
      <p className="mt-3 text-mute">Run a check with four numbers, open the "View all matches" link in your email, or sign in to see saved results.</p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link to="check" className="btn btn-primary no-underline">Check eligibility</Link>
        <Link to="account" className="btn btn-ghost no-underline">Sign in</Link>
      </div>
    </div>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return <p role="status" className="mx-auto max-w-[620px] px-5 pt-24 text-lg sm:px-10 xl:px-16">{children}</p>;
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mx-auto max-w-[620px] px-5 pt-24 sm:px-10 xl:px-16" role="alert">
      <h1 className="text-2xl">Your matches didn't load.</h1>
      <p className="mt-2 text-mute">{message}</p>
      <button type="button" onClick={onRetry} className="btn btn-ghost mt-6">Try again</button>
    </div>
  );
}
