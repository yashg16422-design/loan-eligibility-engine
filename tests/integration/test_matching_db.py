"""Integration tests for Workflow B's SQL (the Treasure Hunt) on a real Postgres.

Runs with PG_TEST_PORT set (see test_ingest_db.py for the docker command). Loads 10k users
through the production ingest code (the real users.csv locally, its synthetic twin in CI:
tests/synthetic_users.py) and a snapshot of the live crawled products, then proves the
optimized class-based pipeline gives EXACTLY the same matches as the naive per-user
evaluation.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import psycopg
import pytest

from loan_engine.common.secrets import DbCredentials
from loan_engine.common.validation import DEFAULT_RULES
from loan_engine.ingest import handler as ingest
from loan_engine.ingest.events import UploadRef
from tests.synthetic_users import users_csv_bytes

PORT = os.environ.get("PG_TEST_PORT")
pytestmark = pytest.mark.skipif(not PORT, reason="set PG_TEST_PORT to run DB integration tests")

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "tests" / "fixtures" / "products_snapshot.json"
CREDS = DbCredentials("postgres", os.environ.get("PG_TEST_PASSWORD", "localtest"))
PROMPT_VERSION = "test_v1"


def sql(name: str) -> str:
    """Load an n8n query and convert its $1-style params to psycopg's %(pN)s style."""
    text = (ROOT / "sql" / "matching" / name).read_text()
    return re.sub(r"\$(\d+)", r"%(p\1)s", text.replace("%", "%%"))


def run_sql(db: psycopg.Connection, name: str, *params: object) -> dict:
    cur = db.execute(sql(name), {f"p{i + 1}": p for i, p in enumerate(params)})
    names = [c.name for c in cur.description or []]
    return dict(zip(names, cur.fetchone() or (), strict=True))


@pytest.fixture(scope="module")
def db() -> psycopg.Connection:
    """Fresh schema (all numbered migrations), 10k real users, the live product snapshot."""
    conn = psycopg.connect(
        host="localhost",
        port=int(PORT or 0),
        dbname="app",
        user=CREDS.username,
        password=CREDS.password,
        autocommit=True,
    )
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    for migration in sorted((ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql")):
        conn.execute(migration.read_text())

    # Users go in through the production ingest path.
    job_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO upload_jobs (job_id, s3_key) VALUES (%s, %s)", (job_id, f"raw/{job_id}.csv")
    )

    class S3:
        def get_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
            import io

            return {"Body": io.BytesIO(users_csv_bytes())}

    deps = ingest.Dependencies(
        "localhost", "x", int(PORT or 0), DEFAULT_RULES, ingest.NoopNotifier(), S3()
    )
    ingest.cached_db_credentials = lambda arn: CREDS  # type: ignore[assignment]
    ingest.process_upload(UploadRef("b", f"raw/{job_id}.csv", job_id), 1, deps)

    cols = [
        "product_id",
        "lender",
        "lender_key",
        "channel",
        "source_url",
        "product_name",
        "interest_rate_min",
        "interest_rate_max",
        "rate_type",
        "min_monthly_income",
        "min_credit_score",
        "max_credit_score",
        "min_age",
        "max_age",
        "employment_types",
        "other_criteria_text",
        "verification",
        "criteria_hash",
    ]
    insert = (
        f"INSERT INTO loan_products ({', '.join(cols)}) "
        f"VALUES ({', '.join(f'%({c})s' for c in cols)})"
    )
    for p in json.loads(PRODUCTS.read_text()):
        conn.execute(insert, p)
    # Compiled residual rules for a few real products, with awkward thresholds that are NOT
    # hard-criteria cut points (742, 99_999, 30): the classes must still stay exact.
    texts = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT other_criteria_text FROM loan_products "
            "WHERE other_criteria_text IS NOT NULL ORDER BY 1 LIMIT 3"
        )
    ]
    rules = [
        [{"field": "credit_score", "op": ">=", "value": 742, "applies_to": "any"}],
        [
            {"field": "monthly_income", "op": "<=", "value": 99999, "applies_to": "salaried"},
            {"field": "age", "op": ">=", "value": 30, "applies_to": "any"},
        ],
        [],  # compiled, nothing checkable, no requirements -> eligible via llm_rules
    ]
    reqs = [["2 years work experience"], [], []]
    for text, rule, req in zip(texts, rules, reqs, strict=True):
        conn.execute(
            "INSERT INTO criteria_rules "
            "(criteria_text_hash, prompt_version, rules, requirements, model_id) "
            "VALUES (encode(sha256(convert_to(%s, 'UTF8')), 'hex'), %s, %s, %s, 'test')",
            (text, PROMPT_VERSION, json.dumps(rule), json.dumps(req)),
        )
    conn.job_id = job_id  # type: ignore[attr-defined]
    yield conn
    conn.close()


def stage3(db: psycopg.Connection, run_id: str) -> dict:
    """What Workflow B does after Stage 1: refresh statistics, then expand + diff."""
    db.execute((ROOT / "sql" / "matching" / "refresh_stats.sql").read_text())
    return run_sql(db, "stage3_expand.sql", run_id)


def new_run(db: psycopg.Connection) -> str:
    return str(
        db.execute(
            "INSERT INTO pipeline_runs (mode, job_id) VALUES ('upload', %s) RETURNING run_id",
            (db.job_id,),
        ).fetchone()[0]
    )  # type: ignore[attr-defined]


def test_pipeline_is_exact_and_idempotent(db):
    run1 = new_run(db)
    funnel = run_sql(db, "stage1_classes.sql", run1, PROMPT_VERSION)
    expand = stage3(db, run1)
    proof = run_sql(db, "brute_force_check.sql", run1, PROMPT_VERSION)
    print("\nFUNNEL", {k: v for k, v in funnel.items() if k != "cuts"})
    print("CUTS", funnel["cuts"])
    print("EXPAND", expand)
    print("PROOF", proof)

    assert funnel["users_in"] == 10000
    assert funnel["naive_pairs"] == 10000 * funnel["products_in"]
    assert funnel["classes"] < 1000  # thousands of users collapse into a few hundred classes
    assert (
        742 in funnel["cuts"]["score"] and 100000 in funnel["cuts"]["income"]
    )  # rule values became cuts
    assert funnel["not_eligible_pairs"] > 0  # the residual rules really reject some classes
    assert proof["mismatches"] == 0 and proof["correctness_ok"] is True
    assert expand["matches_new"] == proof["naive_matches"]

    # Same users again: nothing new, nothing superseded (idempotent re-run, no emails).
    run2 = new_run(db)
    run_sql(db, "stage1_classes.sql", run2, PROMPT_VERSION)
    again = stage3(db, run2)
    assert (again["matches_new"], again["matches_superseded"], again["matches_updated"]) == (
        0,
        0,
        0,
    )
    assert run_sql(db, "brute_force_check.sql", run2, PROMPT_VERSION)["mismatches"] == 0


def test_lower_income_supersedes_matches(db):
    """A user whose income drops below a lender minimum loses that match (no email)."""
    user_id, before = db.execute(
        "SELECT user_id, count(*) FROM matches WHERE status = 'active' GROUP BY user_id "
        "ORDER BY count(*) DESC LIMIT 1"
    ).fetchone()
    db.execute("UPDATE users SET monthly_income = 12000 WHERE user_id = %s", (user_id,))
    run3 = new_run(db)
    run_sql(db, "stage1_classes.sql", run3, PROMPT_VERSION)
    result = stage3(db, run3)
    after = db.execute(
        "SELECT count(*) FROM matches WHERE status = 'active' AND user_id = %s", (user_id,)
    ).fetchone()[0]
    assert result["matches_superseded"] > 0
    assert after < before
    assert run_sql(db, "brute_force_check.sql", run3, PROMPT_VERSION)["mismatches"] == 0


def test_product_mode_rematches_only_scoped_products(db):
    """Workflow A changed one product: a product-mode run re-matches ALL users against it,
    and never touches any other product's matches."""
    product_id, before = db.execute(
        "SELECT product_id, count(*) FROM matches WHERE status = 'active' "
        "GROUP BY product_id ORDER BY count(*) DESC LIMIT 1"
    ).fetchone()
    others_before = db.execute(
        "SELECT count(*) FROM matches WHERE status = 'active' AND product_id <> %s", (product_id,)
    ).fetchone()[0]
    # The lender tightened its rule (as a re-crawl would record it).
    db.execute(
        "UPDATE loan_products SET min_credit_score = 820, max_credit_score = NULL "
        "WHERE product_id = %s",
        (product_id,),
    )
    run4 = str(
        db.execute(
            "INSERT INTO pipeline_runs (mode, scope_product_ids) "
            "VALUES ('products', ARRAY[%s]::uuid[]) RETURNING run_id",
            (product_id,),
        ).fetchone()[0]
    )
    funnel = run_sql(db, "stage1_classes.sql", run4, PROMPT_VERSION)
    result = stage3(db, run4)
    after = db.execute(
        "SELECT count(*) FROM matches WHERE status = 'active' AND product_id = %s", (product_id,)
    ).fetchone()[0]
    others_after = db.execute(
        "SELECT count(*) FROM matches WHERE status = 'active' AND product_id <> %s", (product_id,)
    ).fetchone()[0]
    assert funnel["products_in"] == 1 and funnel["users_in"] == 10000
    assert result["matches_superseded"] > 0 and after < before
    assert others_after == others_before  # out-of-scope matches untouched
    assert run_sql(db, "brute_force_check.sql", run4, PROMPT_VERSION)["mismatches"] == 0


def test_dashboard_queries_on_real_matches(db):
    """The api Lambda's dashboard + ops SQL against the matched 10k users (migration 004)."""
    from loan_engine.api import repository

    user_id = db.execute(
        "SELECT user_id FROM matches WHERE status = 'active' GROUP BY user_id "
        "ORDER BY count(*) DESC LIMIT 1"
    ).fetchone()[0]
    me = repository.get_me(db, user_id)
    matches = repository.get_matches(db, user_id)
    assert me["matches"] == len(matches) > 0
    assert me["eligible"] == sum(m["tier"] == "eligible" for m in matches)
    assert me["lenders"] == len({m["lender_key"] for m in matches})
    # Best first: every eligible match comes before every conditional one.
    tiers = [m["tier"] for m in matches]
    assert tiers == sorted(tiers, key=lambda t: t != "eligible")
    assert repository.get_me(db, uuid.uuid4()) is None  # unknown user = "still loading"

    products = repository.get_products(db, PROMPT_VERSION)
    assert (
        len(products)
        == db.execute("SELECT count(*) FROM loan_products WHERE is_active").fetchone()[0]
    )
    assert any(p["compiled_rules"] for p in products)  # the compiled rules come along

    # Preferences: defaults, then an upsert that is read back.
    assert repository.get_preferences(db, user_id)["shortlist"] == []
    pick = [m["product_id"] for m in matches[:3]]
    saved = repository.save_preferences(
        db, user_id, {"shortlist": pick, "top3": pick[:2], "hidden": [], "alerts": True}
    )
    assert saved["top3"] == pick[:2] and saved["alerts"] is True
    again = repository.save_preferences(
        db, user_id, {"shortlist": pick[:1], "top3": [], "hidden": pick[1:], "alerts": False}
    )
    assert repository.get_preferences(db, user_id)["hidden"] == again["hidden"] == pick[1:]

    runs = repository.ops_runs(db)
    assert runs and runs[0]["naive_pairs"] > 0 and "user_id" not in runs[0]
    assert repository.ops_crawl(db)["products"]  # by channel
    assert isinstance(repository.ops_errors(db), list)
    assert repository.instant_checks_last_24h(db) == 0
