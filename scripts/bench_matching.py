#!/usr/bin/env python3
"""Scale benchmark of Workflow B's matching SQL on a LOCAL Postgres (never production).

For each user count it builds a fresh database, loads synthetic users through the production
ingest code (streaming path), loads the live product snapshot and the test compiled rules, then
runs the real sql/matching/*.sql in Workflow B1's order and times every stage:
claim -> Stage 1+2 -> statistics -> pre-write proof -> Stage 3 -> post-write proof.
No LLM is involved at any size: criteria are compiled once per distinct text, not per user.

    PG_TEST_PORT=55432 .venv/bin/python scripts/bench_matching.py 10000 100000 1000000 \\
        --out docs/evidence/bench_matching_2026-10-11.json
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.integration.matching_setup import (  # noqa: E402
    PROMPT_VERSION,
    connect,
    fresh_schema,
    ingest_csv,
    load_products_and_rules,
    run_sql,
)
from tests.synthetic_users import synthetic_users_csv  # noqa: E402


def timed(fn):  # noqa: ANN001, ANN201 - tiny local helper
    started = time.perf_counter()
    result = fn()
    return result, round(time.perf_counter() - started, 1)


def bench(users: int, classes_only: bool = False) -> dict:
    conn = connect()
    fresh_schema(conn)
    load_products_and_rules(conn)
    csv_bytes = synthetic_users_csv(rows=users, seed=users)
    job_id, ingest_s = timed(lambda: ingest_csv(conn, csv_bytes, streaming=True))
    stages: dict[str, float] = {"ingest (streaming)": ingest_s}

    run_id = run_sql(conn, "claim.sql", "upload", str(job_id), "")["run_id"]
    funnel, stages["stage 1+2: classes and decisions"] = timed(
        lambda: run_sql(conn, "stage1_classes.sql", run_id, PROMPT_VERSION)
    )
    if classes_only:  # the Treasure Hunt claim: decisions stay bounded as users grow
        conn.close()
        return {
            "users": users,
            "products": funnel["products_in"],
            "naive_pairs": funnel["naive_pairs"],
            "classes": funnel["classes"],
            "class_product_decisions": funnel["class_product_pairs"],
            "llm_calls": 0,
            "seconds": stages,
            "scope": "ingest + Stage 1+2 only (no expansion or proofs at this size)",
        }
    _, stages["planner statistics"] = timed(
        lambda: conn.execute((ROOT / "sql" / "matching" / "refresh_stats.sql").read_text())
    )
    pre, stages["pre-write proof (every pair)"] = timed(
        lambda: run_sql(conn, "prewrite_check.sql", run_id, PROMPT_VERSION)
    )
    expand, stages["stage 3: expand, score, diff"] = timed(
        lambda: run_sql(conn, "stage3_expand.sql", run_id)
    )
    post, stages["post-write proof (every pair)"] = timed(
        lambda: run_sql(conn, "brute_force_check.sql", run_id, PROMPT_VERSION)
    )
    conn.close()
    matching = sum(v for k, v in stages.items() if not k.startswith("ingest"))
    return {
        "users": users,
        "products": funnel["products_in"],
        "naive_pairs": funnel["naive_pairs"],
        "classes": funnel["classes"],
        "class_product_decisions": funnel["class_product_pairs"],
        "matches_written": expand["matches_new"],
        "llm_calls": 0,
        "prewrite_mismatches": pre["mismatches"],
        "postwrite_mismatches": post["mismatches"],
        "seconds": stages,
        "matching_seconds_total": round(matching, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sizes", type=int, nargs="+")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--classes-only-from",
        type=int,
        default=10**9,
        help="from this many users, run ingest + Stage 1+2 only",
    )
    args = parser.parse_args()
    results = []
    for n in args.sizes:
        print(f"running {n:,} users ...", file=sys.stderr, flush=True)
        results.append(bench(n, classes_only=n >= args.classes_only_from))
        print(json.dumps(results[-1]), file=sys.stderr, flush=True)
    report = {
        "machine": f"{platform.machine()} {platform.system()} {platform.release()}, "
        f"Python {platform.python_version()}, Postgres 17 in Docker (local laptop)",
        "note": "Local benchmark, not RDS (db.t4g.micro is far smaller). Products: the 59-product "
        "live snapshot in tests/fixtures; compiled rules: the 3 test rules (others 'may qualify').",
        "results": results,
    }
    print(json.dumps(report, indent=1))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
