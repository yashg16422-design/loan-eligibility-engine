// Small, honest charts: plain elements, real numbers printed next to every bar, no background
// tracks, no decoration. A bar's length transitions only when its value changes, so a chart
// visibly "forms" as a live run reports new numbers, and stays still otherwise.

const fmt = (n: number) => new Intl.NumberFormat("en-IN").format(n);

export interface BarRow {
  label: string;
  value: number;
  note?: string;
  color?: string; // a token, e.g. "var(--color-amber)"
}

/** Horizontal bars. `log` for funnels spanning 590,000 to 5 (the shape of the collapse matters). */
export function HBars({ rows, log = false, unit = "" }: { rows: BarRow[]; log?: boolean; unit?: string }) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  const scale = (v: number) => (v <= 0 ? 0 : log ? Math.max(Math.log10(v + 1) / Math.log10(max + 1), 0.02) : v / max);
  return (
    <ul className="grid gap-4">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-1">
          <span className="truncate text-sm">{r.label}</span>
          <span className="num text-sm">
            {fmt(r.value)}
            {unit}
          </span>
          <span aria-hidden className="col-span-2 block h-2">
            <span
              className="grow-x block h-full"
              style={{ transform: `scaleX(${scale(r.value)})`, background: r.color ?? "var(--color-acc)" }}
            />
          </span>
          {r.note && <span className="label col-span-2">{r.note}</span>}
        </li>
      ))}
    </ul>
  );
}

/** Vertical columns for a distribution (income bands, score bands, ages, matches per user). */
export function Columns({ bands, color = "var(--color-acc-2)", height = 168 }: { bands: { label: string; n: number }[]; color?: string; height?: number }) {
  const max = Math.max(...bands.map((b) => b.n), 1);
  const total = bands.reduce((s, b) => s + b.n, 0);
  return (
    <figure>
      <div className="grid items-end gap-3" style={{ gridTemplateColumns: `repeat(${bands.length}, minmax(0, 1fr))`, height }}>
        {bands.map((b) => (
          <div key={b.label} className="flex h-full flex-col justify-end" title={`${b.label}: ${fmt(b.n)}`}>
            <span className="num mb-1 text-center text-xs text-mute">{b.n ? fmt(b.n) : ""}</span>
            <span className="grow-y block w-full" style={{ height: "100%", transform: `scaleY(${b.n / max})`, background: color }} />
          </div>
        ))}
      </div>
      <figcaption className="mt-3 grid gap-3" style={{ gridTemplateColumns: `repeat(${bands.length}, minmax(0, 1fr))` }}>
        {bands.map((b) => (
          <span key={b.label} className="text-center font-mono text-[0.68rem] leading-tight whitespace-nowrap text-mute">
            {b.label}
          </span>
        ))}
      </figcaption>
      <span className="sr-only">
        {bands.map((b) => `${b.label}: ${fmt(b.n)} of ${fmt(total)}`).join("; ")}
      </span>
    </figure>
  );
}

/** One bar split into parts (eligible vs may qualify, channels), with a legend. */
export function Split({ parts }: { parts: { label: string; n: number; color: string }[] }) {
  const total = parts.reduce((s, p) => s + p.n, 0) || 1;
  return (
    <figure>
      <div aria-hidden className="flex h-4 w-full gap-px overflow-hidden">
        {parts.map((p) => (
          <span key={p.label} className="block h-full transition-[flex-grow] duration-500" style={{ flexGrow: p.n, background: p.color }} />
        ))}
      </div>
      <figcaption className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {parts.map((p) => (
          <span key={p.label} className="inline-flex items-center gap-2">
            <span aria-hidden className="size-2.5" style={{ background: p.color }} />
            {p.label} <span className="num text-mute">{fmt(p.n)} ({Math.round((p.n / total) * 100)}%)</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
