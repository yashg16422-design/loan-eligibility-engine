"""Preview Workflow A's extraction on saved fixtures, using the production code paths.

    fixture HTML -> n8n/code/sections.js -> Nova Pro (prompt vN, ONE batched call)
                 -> n8n/code/normalize.js -> product rows (+ verification verdicts)

The JS files are the exact ones pasted into the n8n Code nodes (run here with Node),
so a prompt or parser change can be checked on real pages before touching n8n.

Usage:
  eval "$(aws configure export-credentials --format env)"   # if using `aws login`
  .venv/bin/python scripts/extract_preview.py FIXTURE_DIR bankbazaar:iifl paisabazaar:hdfc-bank
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "amazon.nova-pro-v1:0"


def run_js(module: str, function: str, payload: object) -> object:
    """Call an exported function of an n8n/code module with Node, JSON in/out."""
    script = (
        f"const m=require({json.dumps(str(ROOT / 'n8n' / 'code' / module))});"
        "let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{"
        f"process.stdout.write(JSON.stringify(m.{function}(JSON.parse(d))))}})"
    )
    out = subprocess.run(
        ["node", "-e", script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def load_prompt(version: str) -> tuple[str, str]:
    text = (ROOT / "n8n" / "prompts" / f"extract_criteria_{version}.md").read_text()
    system = text.split("## System prompt")[1].split("## User message template")[0].strip()
    head = text.split("## User message template")[1].split("{{#each pages}}")[0].strip()
    return system, head


def describe(row: dict) -> str:
    """Four readable lines per product row."""
    r = row
    evidence = r["raw_extracted"]["criteria"][0].get("evidence", "")[:120]
    lines = [
        f"{r['verification']:10} {r['product_name']}",
        f"           age {r['min_age']}-{r['max_age']}  income>={r['min_monthly_income']}"
        f"  cibil>={r['min_credit_score']}",
        f"           rate {r['interest_rate_min']}-{r['interest_rate_max']}%"
        f"  amount<={r['loan_amount_max']}  tenure<={r['tenure_months_max']}m",
    ]
    if r["other_criteria_text"]:
        lines.append(f"           conditions: {r['other_criteria_text'][:160]}")
    lines.append(f"           evidence: {evidence!r}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixtures", type=Path)
    ap.add_argument("pages", nargs="+", help="channel:lender_slug")
    ap.add_argument("--prompt", default="v2")
    ap.add_argument("--dump", type=Path, help="write sections + raw extractions as JSON")
    args = ap.parse_args()

    inventory = {
        (r["channel"], r["lender"]): r["url"]
        for r in json.loads((ROOT / "docs/crawl_inventory.json").read_text())
    }
    pages = []
    for ref in args.pages:
        channel, slug = ref.split(":", 1)
        html = (args.fixtures / channel / f"{slug}.html").read_text(encoding="utf-8")
        sections = run_js("sections.js", "extractSections", html)
        pages.append(
            {
                "page_id": ref,
                "channel": channel,
                "lender_slug": slug,
                "url": inventory[(channel, slug)],
                **sections,
            }
        )

    system, head = load_prompt(args.prompt)
    body = (
        head
        + "\n"
        + "".join(
            f"\n=== PAGE {p['page_id']} | source: {p['channel']} | url: {p['url']} ===\n"
            f"--- ELIGIBILITY SECTION ---\n{p['eligibility_text']}\n"
            f"--- INTEREST RATE SECTION ---\n{p['rates_text']}\n"
            for p in pages
        )
    )
    client = boto3.client("bedrock-runtime", region_name="ap-southeast-2")
    started = time.monotonic()
    response = client.converse(
        modelId=MODEL_ID,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": body}]}],
        inferenceConfig={"temperature": 0, "maxTokens": 4000},
    )
    seconds = time.monotonic() - started
    raw = response["output"]["message"]["content"][0]["text"].strip()
    extractions = {
        e["page_id"]: e for e in json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw))
    }
    if args.dump:
        dump = {"pages": pages, "extractions": extractions}
        args.dump.write_text(json.dumps(dump, ensure_ascii=False, indent=1))
    usage = response["usage"]
    print(
        f"1 batched call, {len(pages)} pages, {seconds:.1f}s, tokens in={usage['inputTokens']} "
        f"out={usage['outputTokens']}\n"
    )

    for page in pages:
        page["extraction"] = extractions.get(page["page_id"], {})
        for row in run_js("normalize.js", "toProducts", page):
            print(describe(row))


if __name__ == "__main__":
    main()
