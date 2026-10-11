#!/usr/bin/env python3
"""Draw the Treasure Hunt funnel (docs/treasure_hunt_funnel.svg) from the evidence file.

Every number is read from docs/evidence/pipeline_runs_2026-10-10.json (the headline run on the
real 10,000-user users.csv), so the figure can never drift from the measurement. Bars are on a
log scale: the stages differ by five orders of magnitude.

    .venv/bin/python scripts/funnel_svg.py          # rewrites docs/treasure_hunt_funnel.svg
    .venv/bin/python scripts/funnel_svg.py --check  # fails if the committed SVG is stale
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "pipeline_runs_2026-10-10.json"
OUT = ROOT / "docs" / "treasure_hunt_funnel.svg"
RUN = "e7115e09-6bc3-4a23-ada2-f15f0de31d02"

WIDTH, LEFT, BAR_MAX, ROW = 860, 300, 440, 58
X = "\u00d7"  # the multiplication sign, written as an escape (no ambiguous glyph in source)


def stages(run: dict) -> list[tuple[str, int, str]]:
    return [
        (f"User {X} product pairs (naive)", run["naive_pairs"], "every user against every product"),
        ("Pairs passing published rules", run["pairs_after_sql"], "SQL hard filter on real values"),
        (f"Class {X} product decisions", run["class_product_pairs"], f"{run['classes']} classes"),
        ("LLM calls", run["llm_calls"], "one per batch of distinct criteria texts"),
        ("Mismatches vs brute force", 0 if run["correctness_ok"] else -1, "every pair re-checked"),
    ]


def render(run: dict) -> str:
    rows = stages(run)
    top = math.log10(rows[0][1])
    height = 70 + ROW * len(rows) + 30
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'font-family="Helvetica, Arial, sans-serif" role="img" '
        f'aria-label="Treasure Hunt funnel for the 10,000-user run">',
        f'<rect width="{WIDTH}" height="{height}" fill="#ffffff"/>',
        '<text x="24" y="34" font-size="18" font-weight="700" fill="#111">'
        f"The Optimization Treasure Hunt: 10,000 users {X} 59 products</text>",
        '<text x="24" y="54" font-size="12" fill="#555">'
        f"Measured run {RUN[:8]} (pipeline_runs). Log scale.</text>",
    ]
    for i, (label, value, note) in enumerate(rows):
        y = 74 + ROW * i
        width = BAR_MAX * (math.log10(value) / top) if value > 1 else (3 if value == 1 else 0)
        color = "#2b6cb0" if i < 3 else ("#d69e2e" if i == 3 else "#2f855a")
        parts += [
            f'<text x="24" y="{y + 18}" font-size="13" fill="#111">{escape(label)}</text>',
            f'<text x="24" y="{y + 34}" font-size="11" fill="#666">{escape(note)}</text>',
            f'<rect x="{LEFT}" y="{y + 6}" width="{width:.1f}" height="26" rx="3" fill="{color}"/>',
            f'<text x="{LEFT + width + 10:.1f}" y="{y + 24}" font-size="15" font-weight="700" '
            f'fill="#111">{value:,}</text>',
        ]
    parts.append(
        f'<text x="24" y="{height - 14}" font-size="11" fill="#555">'
        "Later runs: 0 LLM calls (every criteria text cached). Source: "
        "docs/evidence/pipeline_runs_2026-10-10.json</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    run = next(r for r in json.loads(EVIDENCE.read_text()) if r["run_id"] == RUN)
    svg = render(run)
    if args.check:
        if not OUT.exists() or OUT.read_text() != svg:
            sys.exit("docs/treasure_hunt_funnel.svg is stale: run scripts/funnel_svg.py")
        return
    OUT.write_text(svg)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
