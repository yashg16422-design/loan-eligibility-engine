"""Golden master: the visible outcome of ingest + matching must not change by accident.

Builds a fresh database, ingests the pinned synthetic 10k file (plus a few bad rows) through
the production ingest code, runs Workflow B's SQL in order (claim -> Stage 1+2 -> statistics
-> pre-write proof -> Stage 3 -> post-write proof) and compares an order-independent
fingerprint with tests/fixtures/golden_fingerprint.json.

The fingerprint may only change in a commit that intends to change outcomes, and that commit
must say why. To regenerate it:
    GOLDEN_UPDATE=1 PG_TEST_PORT=55432 pytest tests/integration/test_golden.py
"""

from __future__ import annotations

import hashlib
import json
import os

import psycopg
import pytest

from tests.integration.matching_setup import (
    PORT,
    PROMPT_VERSION,
    ROOT,
    connect,
    fresh_schema,
    ingest_csv,
    load_products_and_rules,
    run_sql,
    sql,
    stage3,
)
from tests.synthetic_users import synthetic_users_csv

pytestmark = pytest.mark.skipif(not PORT, reason="set PG_TEST_PORT to run DB integration tests")

GOLDEN = ROOT / "tests" / "fixtures" / "golden_fingerprint.json"
# One row per reject reason the validator knows, plus a duplicate of the first data row
# (the duplicate wins, the original is rejected as duplicate_in_file).
BAD_ROWS = [
    "not-a-uuid,Bad Id,bad.id@example.com,50000,700,Salaried,30",
    "8f14e45f-ceea-467a-9575-0b6bd2e5a001,Bad Email,not-an-email,50000,700,Salaried,30",
    "8f14e45f-ceea-467a-9575-0b6bd2e5a002,Low Score,low.score@example.com,50000,120,Salaried,30",
    "8f14e45f-ceea-467a-9575-0b6bd2e5a003,Bad Job,bad.job@example.com,50000,700,Astronaut,30",
    "8f14e45f-ceea-467a-9575-0b6bd2e5a004,Too Young,too.young@example.com,50000,700,Salaried,12",
    "8f14e45f-ceea-467a-9575-0b6bd2e5a005,Short Row,short.row@example.com,50000",
]
COUNTERS = (
    "users_in",
    "products_in",
    "naive_pairs",
    "classes",
    "class_product_pairs",
    "pairs_after_sql",
    "rule_decided",
    "llm_candidates",
    "not_eligible_pairs",
    "residual_texts",
)


def golden_csv() -> bytes:
    base = synthetic_users_csv().decode()
    first_data_row = base.split("\r\n")[1]
    extra = [*BAD_ROWS, first_data_row]
    return (base + "\r\n".join(extra) + "\r\n").encode()


def claim(db: psycopg.Connection, job_id: object) -> str:
    return run_sql(db, "claim.sql", "upload", str(job_id), "")["run_id"]


def match(db: psycopg.Connection, job_id: object) -> dict:
    """Workflow B1 for one upload, in production order."""
    run_id = claim(db, job_id)
    funnel = run_sql(db, "stage1_classes.sql", run_id, PROMPT_VERSION)
    db.execute((ROOT / "sql" / "matching" / "refresh_stats.sql").read_text())
    prewrite = run_sql(db, "prewrite_check.sql", run_id, PROMPT_VERSION)
    assert prewrite["prewrite_ok"] is True and prewrite["users_without_class"] == 0
    expand = stage3(db, run_id)
    proof = run_sql(db, "brute_force_check.sql", run_id, PROMPT_VERSION)
    return {"funnel": funnel, "expand": expand, "proof": proof}


def ingest_counts(db: psycopg.Connection, job_id: object) -> dict:
    row = db.execute(
        "SELECT status, total_rows, inserted, updated, unchanged, rejected "
        "FROM upload_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    reasons = db.execute(
        "SELECT reason, count(*) FROM upload_rejects WHERE job_id = %s GROUP BY 1 ORDER BY 1",
        (job_id,),
    ).fetchall()
    keys = ("status", "total_rows", "inserted", "updated", "unchanged", "rejected")
    return {**dict(zip(keys, row, strict=True)), "reject_reasons": dict(reasons)}


def fingerprint(db: psycopg.Connection, job_id: object, result: dict) -> dict:
    rows = db.execute(
        "SELECT user_id::text, product_id::text, tier, coalesce(requirements, ''), stage_decided "
        "FROM matches WHERE status = 'active'"
    ).fetchall()
    lines = sorted("|".join(r) for r in rows)
    by_tier = db.execute(
        "SELECT tier, count(*) FROM matches WHERE status = 'active' GROUP BY 1 ORDER BY 1"
    ).fetchall()
    by_product = db.execute(
        "SELECT product_id::text, count(*) FROM matches WHERE status = 'active' "
        "GROUP BY 1 ORDER BY 1"
    ).fetchall()
    return {
        "ingest": ingest_counts(db, job_id),
        "matching": {k: result["funnel"][k] for k in COUNTERS}
        | {
            "matches_new": result["expand"]["matches_new"],
            "cuts": result["funnel"]["cuts"],
            "correctness_ok": result["proof"]["correctness_ok"],
            "mismatches": result["proof"]["mismatches"],
        },
        "matches_by_tier": dict(by_tier),
        "matches_by_product": dict(by_product),
        "matches_sha256": hashlib.sha256("\n".join(lines).encode()).hexdigest(),
    }


@pytest.fixture(scope="module")
def db() -> psycopg.Connection:
    conn = connect()
    fresh_schema(conn)
    load_products_and_rules(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def first_upload(db) -> tuple[object, dict]:
    job_id = ingest_csv(db, golden_csv())
    return job_id, match(db, job_id)


def test_golden_fingerprint_unchanged(db, first_upload):
    job_id, result = first_upload
    got = fingerprint(db, job_id, result)
    if os.environ.get("GOLDEN_UPDATE") == "1":
        GOLDEN.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN.read_text())
    # Compare section by section so a failure names what changed.
    for section in expected:
        assert got[section] == expected[section], f"golden section changed: {section}"
    assert got["matching"]["correctness_ok"] is True


def test_same_file_again_changes_nothing(db, first_upload):
    """Re-uploading the same file: nothing new in users, matches or emails."""
    job_id = ingest_csv(db, golden_csv())
    counts = ingest_counts(db, job_id)
    assert (counts["inserted"], counts["updated"]) == (0, 0)
    assert counts["unchanged"] == 10_000
    result = match(db, job_id)
    assert (result["expand"]["matches_new"], result["expand"]["matches_superseded"]) == (0, 0)
    assert result["proof"]["mismatches"] == 0


def test_independent_recompute_matches_the_engine(db, first_upload):
    """scripts/recompute_eligibility.py (plain Python, no SQL) agrees with the analytics chart."""
    import importlib.util
    import sys

    from loan_engine.api import repository

    spec = importlib.util.spec_from_file_location(
        "recompute", ROOT / "scripts" / "recompute_eligibility.py"
    )
    recompute = importlib.util.module_from_spec(spec)
    sys.modules["recompute"] = recompute  # dataclasses look their module up while loading
    spec.loader.exec_module(recompute)  # type: ignore[union-attr]

    job_id, _ = first_upload
    products = db.execute("SELECT coalesce(json_agg(p), '[]') FROM loan_products p").fetchone()[0]
    rules = db.execute(
        "SELECT coalesce(json_agg(r), '[]') FROM criteria_rules r WHERE prompt_version = %s",
        (PROMPT_VERSION,),
    ).fetchone()[0]
    users = recompute.read_users(golden_csv().decode())
    independent = {r["lender"]: r for r in recompute.recompute(users, products, rules)}
    chart = repository.analytics(db, job_id)["top_lenders"]
    assert len(chart) == 10
    for row in chart:
        mine = independent[row["lender"]]
        assert (mine["users"], mine["eligible_users"]) == (row["users"], row["eligible_users"])


def test_workflow_c_records_each_send_so_a_rerun_never_emails_twice(db, first_upload):
    """Workflow C's SQL: crash after 2 of 5 sends, re-run -> only 3 more; finish is idempotent."""
    _, result = first_upload
    run_id = str(result["funnel"]["run_id"])

    def users_to_email() -> list[str]:
        cur = db.execute(sql("notify_users.sql"), {"p1": run_id, "p2": 5})
        return [r[1] for r in cur.fetchall()]

    def record(user_id: str, status: str) -> dict:
        msg = "ses-1" if status == "sent" else ""
        err = "" if status == "sent" else "throttled"
        record = {
            "run_id": run_id,
            "user_id": user_id,
            "alias_email": "a+one@gmail.com",
            "status": status,
            "ses_message_id": msg,
            "error": err,
            "subject": "Subject, with a comma",
            # A real email body: commas, newlines, quotes, rupees (what broke n8n's parameters).
            "body_text": "Hi A, here are your matches.\nProfile: ₹1,31,000/month, 'quoted'",
        }
        return run_sql(db, "notify_record_send.sql", json.dumps(record))

    first = users_to_email()
    assert len(first) == 5
    assert record(first[0], "sent")["matches_marked"] > 0
    stored = db.execute(
        "SELECT subject, body_text FROM notifications WHERE run_id = %s AND user_id = %s",
        (run_id, first[0]),
    ).fetchone()
    assert stored == (
        "Subject, with a comma",
        "Hi A, here are your matches.\nProfile: ₹1,31,000/month, 'quoted'",
    )  # the sent email itself is kept, intact
    record(first[1], "sent")
    # n8n dies here. The re-run picks only the remaining quota, and never the two emailed users.
    again = users_to_email()
    assert len(again) == 3 and not set(again) & set(first[:2])
    failed = record(again[0], "failed")
    assert (failed["recorded"], failed["matches_marked"]) == (1, 0)  # failed: retried later

    with_new = db.execute(
        "SELECT count(DISTINCT user_id) FROM notifications WHERE run_id = %s", (run_id,)
    ).fetchone()[0]
    done = run_sql(db, "notify_finish.sql", run_id)
    assert (done["emails_sent"], done["emails_failed"]) == (2, 1)
    total_users = result["funnel"]["users_in"]
    assert done["emails_skipped_demo"] == total_users - with_new
    # Running the finish step again changes nothing.
    again_done = run_sql(db, "notify_finish.sql", run_id)
    assert again_done["notification_rows"] == 0
    assert again_done["emails_skipped_demo"] == done["emails_skipped_demo"]


def test_workflow_c1_composes_every_skipped_users_email_and_the_loop_ends(db, first_upload):
    """C1's SQL, driven the way C's loop drives it (Python stands in for email.js)."""
    _, result = first_upload
    run_id = str(result["funnel"]["run_id"])
    skipped = db.execute(
        "SELECT count(*) FROM notifications WHERE run_id = %s AND status = 'skipped_demo'",
        (run_id,),
    ).fetchone()[0]
    assert skipped > 1000  # the C test above recorded the rest of the 10k users as skipped

    batches, remaining = 0, None
    while remaining != 0:
        cur = db.execute(sql("notify_compose_batch.sql"), {"p1": run_id, "p2": 500})
        names = [c.name for c in cur.description]
        users = [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
        assert 0 < len(users) <= 500
        assert all(u["picks"] and len(u["picks"]) <= 5 for u in users)
        emails = [
            {"user_id": u["user_id"], "subject": f"s{u['user_id'][:4]}", "body_text": "t"}
            for u in users
        ]
        saved = run_sql(db, "notify_save_composed.sql", run_id, json.dumps(emails))
        assert saved["composed"] == len(users)
        remaining = saved["remaining"]
        batches += 1
        assert batches <= 30
    assert batches == -(-skipped // 500)  # ceil: every batch full except the last
    assert db.execute(
        "SELECT count(*) FROM notifications WHERE run_id = %s AND subject IS NULL", (run_id,)
    ).fetchone() == (0,)
