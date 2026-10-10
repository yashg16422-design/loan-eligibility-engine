import type { Analytics, Band } from "../api/types";
import { EMPLOYMENT_LABEL } from "../lib/format";
import { CHANNEL_LABEL } from "../lib/offers";
import { Columns, HBars, Split } from "../ui/charts";

// Band labels for the server's buckets (loan_engine/api/repository.py _ANALYTICS_SQL).
const LABELS = {
  income: ["< 25k", "25-50k", "50-75k", "75k-1L", "1-1.25L", "1.25L +"],
  score: ["< 650", "650-699", "700-749", "750-799", "800 +"],
  age: ["< 25", "25-29", "30-34", "35-39", "40-44", "45 +"],
  matches: ["0", "1-10", "11-20", "21-30", "31-40", "41 +"],
};

/** Fill the buckets the server omitted (no users there) so every chart has the same axis. */
export function fillBands(bands: Band[], labels: string[]): { label: string; n: number }[] {
  const by = new Map(bands.map((b) => [b.ord, b.n]));
  return labels.map((label, ord) => ({ label, n: by.get(ord) ?? 0 }));
}

const fmt = (n: number) => new Intl.NumberFormat("en-IN").format(n);

export function AnalyticsGrid({ data }: { data: Analytics }) {
  if (data.users === 0) {
    return (
      <p className="box p-7 text-sm text-mute">
        No customers from this upload are in the database (the file changed nobody, or its data was deleted), so there is
        nothing to chart. Upload a file with new or changed customers to see their profile and matches here.
      </p>
    );
  }
  const eligible = data.tiers.find((t) => t.key === "eligible")?.n ?? 0;
  const lenders = [...data.top_lenders]
    .sort((a, b) => b.eligible_users - a.eligible_users || a.lender.localeCompare(b.lender))
    .map((l) => ({ label: l.lender, value: l.eligible_users, note: `${fmt(l.users)} with any offer`, color: "var(--color-acc)" }));
  const conditional = data.tiers.find((t) => t.key === "conditional")?.n ?? 0;
  return (
    <div className="grid gap-px border border-line bg-line lg:grid-cols-3">
      <Cell title="Monthly income" note={`${fmt(data.users)} customers`}>
        <Columns bands={fillBands(data.income_bands, LABELS.income)} color="var(--color-acc-2)" />
      </Cell>
      <Cell title="Credit score" note="CIBIL">
        <Columns bands={fillBands(data.score_bands, LABELS.score)} color="var(--color-teal)" />
      </Cell>
      <Cell title="Age" note="years">
        <Columns bands={fillBands(data.age_bands, LABELS.age)} color="#8f9cf9" />
      </Cell>
      <Cell title="How they earn">
        <Split
          parts={data.employment.map((e, i) => ({
            label: EMPLOYMENT_LABEL[e.key],
            n: e.n,
            color: ["var(--color-acc-2)", "var(--color-teal)", "#8f9cf9"][i % 3],
          }))}
        />
      </Cell>
      <Cell title="Matches per user" note={`${fmt(data.users_with_eligible)} qualify outright somewhere`}>
        <Columns bands={fillBands(data.matches_per_user, LABELS.matches)} color="var(--color-peri)" />
      </Cell>
      <Cell title="Eligible or may qualify" note={`${fmt(data.matches)} matches, then by platform`}>
        <Split
          parts={[
            { label: "Eligible", n: eligible, color: "var(--color-acc)" },
            { label: "May qualify", n: conditional, color: "var(--color-amber)" },
          ]}
        />
        <div className="mt-8">
          <Split parts={data.channels.map((c, i) => ({ label: CHANNEL_LABEL[c.key], n: c.n, color: ["var(--color-acc-2)", "var(--color-teal)", "#8f9cf9"][i % 3] }))} />
        </div>
      </Cell>
      <div className="bg-bg p-7 lg:col-span-3">
        <h3 className="text-lg font-light">Where these customers qualify outright</h3>
        <p className="mt-1 text-sm text-mute">
          Customers who meet every rule the lender publishes, on at least one platform. A lender that publishes no criteria
          counts as "may qualify", never here.
        </p>
        <div className="mt-7 grid gap-x-16 lg:grid-cols-2">
          <HBars rows={lenders.slice(0, 5)} />
          <HBars rows={lenders.slice(5, 10)} />
        </div>
      </div>
    </div>
  );
}

function Cell({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="bg-bg p-7">
      <h3 className="text-lg font-light">{title}</h3>
      {note && <p className="label mt-2">{note}</p>}
      <div className="mt-7">{children}</div>
    </section>
  );
}
