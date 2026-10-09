import { SealCheck } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import type { Run } from "../api/types";

interface Stage {
  key: string;
  value: number;
  label: string;
  detail: string;
}

// The order IS the content here (each stage feeds the next), so the stages are numbered.
function stages(r: Run): Stage[] {
  return [
    { key: "pairs", value: r.naive_pairs ?? 0, label: "Every user and product pair",
      detail: `${fmt(r.users_in)} users x ${fmt(r.products_in)} products: what asking an AI about each pair would cost` },
    { key: "classes", value: r.classes ?? 0, label: "Equivalence classes",
      detail: "Users who fall between the same lender thresholds get identical answers" },
    { key: "decisions", value: r.class_product_pairs ?? 0, label: "Class and product decisions",
      detail: "Hard criteria and compiled rules, decided once per class in SQL" },
    { key: "ai", value: r.llm_calls ?? 0, label: "AI calls",
      detail: r.llm_calls ? `Free-text criteria compiled into rules, then cached` : "Every criterion was already compiled and cached" },
    { key: "matches", value: (r.matches_new ?? 0) + (r.matches_unchanged ?? 0), label: "Matches",
      detail: `${fmt(r.matches_new)} new, ${fmt(r.matches_superseded)} withdrawn, ${fmt(r.matches_unchanged)} unchanged` },
    { key: "emails", value: r.emails_sent ?? 0, label: "Emails sent",
      detail: r.emails_skipped_demo ? `${fmt(r.emails_skipped_demo)} more held back by the demo cap` : "One per user with new matches" },
  ];
}

const fmt = (n: number | null | undefined) => (n == null ? "-" : new Intl.NumberFormat("en-IN").format(n));

export function Pipeline({ run }: { run: Run }) {
  const reduce = useReducedMotion();
  const list = stages(run);
  const max = Math.max(...list.map((s) => s.value), 1);
  const step = 0.28; // seconds between stages: the pipeline "builds" left to right, once

  return (
    <figure aria-label="How this matching run narrowed the work">
      <ol className="grid gap-0 md:grid-cols-6">
        {list.map((s, i) => (
          <motion.li
            key={`${run.run_id}-${s.key}`}
            initial={reduce ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: reduce ? 0 : i * step, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            className="relative grid grid-cols-[28px_1fr] gap-3 pb-8 md:block md:pr-6 md:pb-0"
          >
            {/* Connector to the next stage, with one packet travelling along it. */}
            {i < list.length - 1 && <Connector delay={reduce ? 0 : i * step + 0.2} reduce={!!reduce} />}
            <span className="relative z-10 grid size-7 place-items-center rounded-full border border-line-strong bg-ink text-xs text-muted num md:mb-5">
              {i + 1}
            </span>
            <div>
              <p className="num text-2xl font-medium tracking-tight">{fmt(s.value)}</p>
              <Magnitude value={s.value} max={max} delay={reduce ? 0 : i * step + 0.1} reduce={!!reduce} />
              <p className="mt-2 text-sm font-medium">{s.label}</p>
              <p className="mt-1 text-xs text-muted">{s.detail}</p>
            </div>
          </motion.li>
        ))}
      </ol>
      <figcaption className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-muted">
        {run.correctness_ok && (
          <span className="flex items-center gap-1.5 text-text">
            <SealCheck size={18} weight="fill" className="text-leaf" aria-hidden />
            Same result as checking all {fmt(run.naive_pairs)} pairs one by one
          </span>
        )}
        {run.seconds != null && <span>Finished in <span className="num text-text">{run.seconds} s</span></span>}
        {run.llm_cost_usd_est != null && Number(run.llm_cost_usd_est) > 0 && (
          <span>AI cost <span className="num text-text">${Number(run.llm_cost_usd_est).toFixed(3)}</span></span>
        )}
      </figcaption>
    </figure>
  );
}

/** Bar length on a log scale: the point is the collapse from 590,000 to 5, not exact widths. */
function Magnitude({ value, max, delay, reduce }: { value: number; max: number; delay: number; reduce: boolean }) {
  const width = value > 0 ? Math.max(Math.log10(value + 1) / Math.log10(max + 1), 0.04) : 0;
  return (
    <span aria-hidden className="mt-2 block h-1 w-full max-w-[140px] overflow-hidden rounded-full">
      <motion.span
        className="block h-full origin-left rounded-full bg-marigold"
        initial={reduce ? false : { scaleX: 0 }}
        animate={{ scaleX: width }}
        transition={{ delay, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      />
    </span>
  );
}

function Connector({ delay, reduce }: { delay: number; reduce: boolean }) {
  return (
    <span aria-hidden className="absolute top-7 left-[13px] h-[calc(100%-28px)] w-px md:top-[13px] md:left-9 md:h-px md:w-[calc(100%-36px)]">
      <motion.span
        className="absolute inset-0 origin-top bg-line-strong md:origin-left"
        initial={reduce ? false : { scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ delay, duration: 0.3, ease: "easeOut" }}
      />
      {!reduce && (
        <motion.span
          className="absolute size-1.5 -translate-x-[2.5px] rounded-full bg-marigold md:-translate-y-[2.5px] md:translate-x-0"
          initial={{ opacity: 0, top: "0%", left: "0%" }}
          animate={{ opacity: [0, 1, 1, 0], top: ["0%", "0%", "100%", "100%"], left: ["0%", "0%", "100%", "100%"] }}
          transition={{ delay: delay + 0.15, duration: 0.7, ease: "easeInOut" }}
        />
      )}
    </span>
  );
}
