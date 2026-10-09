import { ArrowSquareOut, BookmarkSimple, CaretDown, EyeSlash, Scales, SealCheck } from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useId, useState } from "react";
import type { Match, Profile } from "../api/types";
import { displayParts, fitParts } from "../lib/fit";
import { rupeesShort } from "../lib/format";
import { CHANNEL_LABEL, CHANNEL_PHRASE, type LenderOffer } from "../lib/offers";

interface Props {
  offer: LenderOffer;
  profile: Profile;
  saved: boolean;
  comparing: boolean;
  compareFull: boolean;
  hidden: boolean;
  onSave: () => void;
  onCompare: () => void;
  onHide: () => void;
}

export function OfferRow({ offer, profile, saved, comparing, compareFull, hidden, onSave, onCompare, onHide }: Props) {
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();
  const panelId = useId();
  const m = offer.best;

  return (
    <li className={`border-b border-line ${hidden ? "opacity-60" : ""}`}>
      {/* Container query: the table layout only when the LIST is wide enough, not the window. */}
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-1 px-1 py-4 @3xl:grid-cols-[minmax(0,1fr)_170px_140px_112px_116px] @3xl:items-center">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={panelId}
          className="group flex min-w-0 items-start gap-3 text-left"
        >
          <CaretDown size={16} aria-hidden
            className={`mt-1 shrink-0 text-muted transition-transform duration-200 group-hover:text-text ${open ? "rotate-180" : ""}`} />
          <span className="min-w-0">
            <span className="block truncate font-medium">{offer.lender}</span>
            <span className="mt-0.5 block text-sm text-muted">
              Best on {CHANNEL_PHRASE[m.channel]}
              {offer.others.length > 0 && `, also on ${offer.others.map((o) => CHANNEL_PHRASE[o.channel]).join(" and ")}`}
            </span>
          </span>
        </button>
        {/* Narrow: one quiet facts line under the name. Wide: three aligned columns. */}
        <p className="col-start-1 row-start-2 flex flex-wrap gap-x-4 gap-y-1 pl-7 text-sm @3xl:contents">
          <span className="@3xl:text-right"><Rate min={m.interest_rate_min} max={m.interest_rate_max} /></span>
          <span className="text-muted @3xl:text-right">
            {m.loan_amount_max ? <>up to <span className="num whitespace-nowrap text-text">{rupeesShort(m.loan_amount_max)}</span></> : "Amount not stated"}
          </span>
          <TierBadge tier={m.tier} />
        </p>
        <div className="col-start-2 row-span-2 row-start-1 flex items-center gap-1 @3xl:col-start-auto @3xl:row-span-1 @3xl:row-start-auto">
          <IconToggle label={saved ? "Remove from saved" : "Save offer"} pressed={saved} onClick={onSave}>
            <BookmarkSimple size={18} weight={saved ? "fill" : "regular"} />
          </IconToggle>
          <IconToggle
            label={comparing ? "Remove from comparison" : compareFull ? "Comparison is full (3)" : "Add to comparison"}
            pressed={comparing}
            disabled={!comparing && compareFull}
            onClick={onCompare}
          >
            <Scales size={18} weight={comparing ? "fill" : "regular"} />
          </IconToggle>
          <IconToggle label={hidden ? "Show this offer again" : "Not interested"} pressed={hidden} onClick={onHide}>
            <EyeSlash size={18} />
          </IconToggle>
        </div>
      </div>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={panelId}
            initial={reduce ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={reduce ? undefined : { height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="grid gap-8 pb-6 pl-8 sm:grid-cols-2">
              <FitBreakdown match={m} profile={profile} />
              <div className="grid content-start gap-6">
                <section>
                  <h4 className="text-sm font-medium">You'll also need</h4>
                  <p className="mt-1.5 text-sm text-muted">
                    {m.requirements ?? "Nothing beyond the published criteria above."}
                  </p>
                </section>
                {offer.others.length > 0 && (
                  <section>
                    <h4 className="text-sm font-medium">Same lender, other platforms</h4>
                    <ul className="mt-1.5 grid gap-1 text-sm">
                      {offer.others.map((o) => (
                        <li key={o.product_id} className="flex justify-between gap-4 text-muted">
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
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

function FitBreakdown({ match, profile }: { match: Match; profile: Profile }) {
  const parts = fitParts(match, profile);
  const shown = displayParts(parts, match.fit_score);
  return (
    <section aria-label="Why this offer fits">
      <div className="flex items-baseline justify-between">
        <h4 className="text-sm font-medium">Why it fits</h4>
        <p className="text-sm text-muted">
          Fit <span className="num text-text">{match.fit_score}</span> of 100
        </p>
      </div>
      <div className="mt-3 flex h-2 gap-px overflow-hidden rounded-full" aria-hidden>
        {parts.map((p) => (
          <span key={p.key} style={{ flexGrow: p.points }}
            className={p.key === "tier" ? "bg-marigold" : p.unknown ? "bg-line-strong" : "bg-marigold/55"} />
        ))}
        <span style={{ flexGrow: Math.max(100 - parts.reduce((s, p) => s + p.points, 0), 0) }} />
      </div>
      <dl className="mt-3 grid gap-1.5 text-sm">
        {parts.map((p, i) => (
          <div key={p.key} className="flex justify-between gap-4">
            <dt className="text-muted">
              {p.label}
              {p.unknown && <span className="text-xs"> (no minimum published)</span>}
            </dt>
            <dd className="num">
              {shown[i].toFixed(1)}
              <span className="text-muted">/{p.max}</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-muted">
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
    <section className="text-sm">
      <p className="flex items-center gap-1.5 text-muted">
        {verified && <SealCheck size={16} weight="fill" className="text-leaf" aria-hidden />}
        {verified ? "Criteria quoted from the source and verified" : "Criteria could not be fully verified, so treat as may qualify"}
        {seen && `, checked ${seen}`}.
      </p>
      {match.product_url && /^https?:\/\//.test(match.product_url) && (
        <a href={match.product_url} target="_blank" rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-text underline decoration-line-strong hover:decoration-marigold">
          View on {CHANNEL_LABEL[match.channel]}
          <ArrowSquareOut size={14} aria-hidden />
        </a>
      )}
    </section>
  );
}

export function TierBadge({ tier }: { tier: Match["tier"] | "not_eligible" }) {
  if (tier === "not_eligible") return <span className="text-sm text-muted">Out of reach</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      <span aria-hidden className={`size-2 rounded-[2px] ${tier === "eligible" ? "bg-leaf" : "border border-muted"}`} />
      {tier === "eligible" ? "Eligible" : "May qualify"}
    </span>
  );
}

function IconToggle({ label, pressed, disabled, onClick, children }: {
  label: string; pressed: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" aria-label={label} title={label} aria-pressed={pressed} disabled={disabled} onClick={onClick}
      className={`grid size-9 place-items-center rounded-[var(--radius-ctl)] transition-colors duration-150 hover:bg-raise disabled:cursor-not-allowed disabled:opacity-35 ${
        pressed ? "text-marigold" : "text-muted hover:text-text"
      }`}>
      {children}
    </button>
  );
}

/** Numbers in mono (measurements), words in the text face: "9.5% to 21.55%". */
export function Rate({ min, max }: { min: number | null; max: number | null }) {
  if (min == null) return <span className="text-muted">Rate on request</span>;
  if (max == null || max === min) return <span>from <span className="num">{min}%</span></span>;
  return <span className="whitespace-nowrap"><span className="num">{min}%</span> to <span className="num">{max}%</span></span>;
}
