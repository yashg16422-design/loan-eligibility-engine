import { ArrowUpRight, BookmarkSimple, CaretDown, EyeSlash, Scales, SealCheck } from "@phosphor-icons/react";
import { useId, useState } from "react";
import type { Match, Profile } from "../api/types";
import { displayParts, fitParts } from "../lib/fit";
import { rupeesShort } from "../lib/format";
import { CHANNEL_LABEL, CHANNEL_PHRASE, type LenderOffer } from "../lib/offers";

export interface RowActions {
  saved: boolean;
  comparing: boolean;
  compareFull: boolean;
  hidden: boolean;
  onSave: () => void;
  onCompare: () => void;
  onHide: () => void;
}

export function OfferRow({ offer, profile, actions }: { offer: LenderOffer; profile: Profile; actions: RowActions }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const m = offer.best;
  return (
    <li className={`border-t border-line first:border-t-0 ${actions.hidden ? "opacity-50" : ""}`}>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 gap-y-1.5 px-6 py-5 @3xl:grid-cols-[minmax(0,1fr)_170px_130px_120px_auto]">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={panel}
          className="group flex min-w-0 items-start gap-3 text-left">
          <CaretDown size={14} aria-hidden className={`mt-1.5 shrink-0 text-mute group-hover:text-fg ${open ? "rotate-180" : ""}`} />
          <span className="min-w-0">
            <span className="block truncate font-medium">{offer.lender}</span>
            <span className="block text-sm text-mute">
              Best on {CHANNEL_PHRASE[m.channel]}
              {offer.others.length > 0 && `, also on ${offer.others.map((o) => CHANNEL_PHRASE[o.channel]).join(" and ")}`}
            </span>
          </span>
        </button>
        <p className="col-start-1 row-start-2 flex flex-wrap gap-x-4 gap-y-1 pl-7 text-sm @3xl:contents">
          <span className="@3xl:text-right"><Rate min={m.interest_rate_min} max={m.interest_rate_max} /></span>
          <span className="text-mute @3xl:text-right">
            {m.loan_amount_max ? <>up to <span className="num text-fg">{rupeesShort(m.loan_amount_max)}</span></> : "Amount not stated"}
          </span>
          <TierBadge tier={m.tier} />
        </p>
        <Actions actions={actions} />
      </div>
      {open && (
        <div id={panel} className="grid gap-8 border-t border-line bg-bg px-6 py-7 pl-13 @3xl:grid-cols-2">
          <FitBreakdown match={m} profile={profile} />
          <div className="grid content-start gap-5 text-sm">
            <section>
              <h4 className="font-medium">You'll also need</h4>
              <p className="mt-1 text-mute">{m.requirements ?? "Nothing beyond the published criteria."}</p>
            </section>
            {offer.others.length > 0 && (
              <section>
                <h4 className="font-medium">Same lender, other platforms</h4>
                <ul className="mt-1 grid gap-1">
                  {offer.others.map((o) => (
                    <li key={o.product_id} className="flex justify-between gap-4 text-mute">
                      <span>{CHANNEL_LABEL[o.channel]}</span>
                      <Rate min={o.interest_rate_min} max={o.interest_rate_max} />
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <Source match={m} />
          </div>
        </div>
      )}
    </li>
  );
}

export function Actions({ actions }: { actions: RowActions }) {
  const { saved, comparing, compareFull, hidden } = actions;
  return (
    <div className="col-start-2 row-span-2 row-start-1 flex items-center @3xl:col-start-auto @3xl:row-span-1 @3xl:row-start-auto">
      <IconToggle label={saved ? "Remove from saved" : "Save offer"} pressed={saved} onClick={actions.onSave}>
        <BookmarkSimple size={18} weight={saved ? "fill" : "regular"} />
      </IconToggle>
      <IconToggle label={comparing ? "Remove from comparison" : compareFull ? "Comparison is full (3)" : "Add to comparison"}
        pressed={comparing} disabled={!comparing && compareFull} onClick={actions.onCompare}>
        <Scales size={18} weight={comparing ? "fill" : "regular"} />
      </IconToggle>
      <IconToggle label={hidden ? "Show this offer again" : "Not interested"} pressed={hidden} onClick={actions.onHide}>
        <EyeSlash size={18} />
      </IconToggle>
    </div>
  );
}

function FitBreakdown({ match, profile }: { match: Match; profile: Profile }) {
  const parts = fitParts(match, profile);
  const shown = displayParts(parts, match.fit_score);
  return (
    <section aria-label="Why this offer fits" className="text-sm">
      <div className="flex items-baseline justify-between">
        <h4 className="font-medium">Why it fits</h4>
        <span className="text-mute">fit <span className="num text-fg">{match.fit_score}</span> of 100</span>
      </div>
      <dl className="mt-3 grid gap-1.5">
        {parts.map((p, i) => (
          <div key={p.key} className="flex justify-between gap-4">
            <dt className="text-mute">{p.label}{p.unknown && <span className="text-xs"> (no minimum published)</span>}</dt>
            <dd className="num">{shown[i].toFixed(1)}<span className="text-mute">/{p.max}</span></dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-mute">
        {match.fit_reasons.income_multiple != null && `Your income is ${match.fit_reasons.income_multiple}x this lender's minimum. `}
        {match.fit_reasons.credit_margin != null &&
          `Your score is ${Math.abs(match.fit_reasons.credit_margin)} points ${match.fit_reasons.credit_margin >= 0 ? "above" : "below"} its minimum.`}
      </p>
    </section>
  );
}

function Source({ match }: { match: Match }) {
  const verified = match.verification === "ok";
  const seen = match.last_seen_at ? new Date(match.last_seen_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : null;
  return (
    <section>
      <p className="flex items-start gap-1.5 text-mute">
        {verified && <SealCheck size={16} weight="fill" className="mt-0.5 shrink-0 text-acc" aria-hidden />}
        {verified ? "Criteria quoted from the source and verified" : "Criteria could not be fully verified, so treat as may qualify"}
        {seen && `, checked ${seen}`}.
      </p>
      {match.product_url && /^https?:\/\//.test(match.product_url) && (
        <a href={match.product_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 underline decoration-line-hi hover:decoration-fg">
          View on {CHANNEL_LABEL[match.channel]} <ArrowUpRight size={14} aria-hidden />
        </a>
      )}
    </section>
  );
}

/** Numbers in mono (measurements), words in the text face: "9.5% to 21.55%". */
export function Rate({ min, max }: { min: number | null; max: number | null }) {
  if (min == null) return <span className="text-mute">Rate on request</span>;
  if (max == null || max === min) return <span>from <span className="num">{min}%</span></span>;
  return <span className="whitespace-nowrap"><span className="num">{min}%</span> to <span className="num">{max}%</span></span>;
}

export function TierBadge({ tier }: { tier: Match["tier"] | "not_eligible" }) {
  const style = tier === "eligible" ? "border-acc text-acc" : tier === "conditional" ? "border-amber/70 text-amber" : "border-coral/70 text-coral";
  const label = tier === "eligible" ? "Eligible" : tier === "conditional" ? "May qualify" : "Not eligible";
  return <span className={`inline-flex h-6 w-fit items-center border px-2 font-mono text-[0.7rem] ${style}`}>{label}</span>;
}

function IconToggle({ label, pressed, disabled, onClick, children }: {
  label: string; pressed: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" aria-label={label} title={label} aria-pressed={pressed} disabled={disabled} onClick={onClick}
      className={`grid size-9 place-items-center transition-colors duration-150 hover:bg-panel-2 disabled:cursor-not-allowed disabled:opacity-30 ${
        pressed ? "text-acc" : "text-mute hover:text-fg"
      }`}>
      {children}
    </button>
  );
}
