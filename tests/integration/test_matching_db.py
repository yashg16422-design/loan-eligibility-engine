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


def test_accounts_and_analytics(db):
    """Migration 005 + the account SQL: first saver owns a profile; analytics are aggregates."""
    from loan_engine.api import repository

    user_a, user_b = [r[0] for r in db.execute("SELECT user_id FROM users LIMIT 2").fetchall()]
    repository.upsert_account(db, "sub-1", "one@example.org")
    repository.upsert_account(db, "sub-2", "two@example.org")
    assert repository.claim_profile(db, "sub-1", user_a) == "saved"
    assert repository.claim_profile(db, "sub-1", user_a) == "already_saved"
    assert repository.claim_profile(db, "sub-2", user_a) == "taken"  # first saver owns it
    assert repository.claim_profile(db, "sub-2", uuid.uuid4()) == "not_found"
    assert repository.owns_profile(db, "sub-1", user_a) and not repository.owns_profile(
        db, "sub-2", user_a
    )
    profiles = repository.account_profiles(db, "sub-1")
    assert [p["user_id"] for p in profiles] == [user_a] and profiles[0]["matches"] >= 0
    repository.set_daily_picks(db, "sub-1", False)
    assert repository.upsert_account(db, "sub-1", "one@example.org")["daily_picks"] is False
    assert repository.claim_profile(db, "sub-2", user_b) == "saved"

    every = repository.analytics(db, None)
    assert every["users"] == db.execute("SELECT count(*) FROM users").fetchone()[0]
    assert sum(b["n"] for b in every["income_bands"]) == every["users"]
    assert sum(b["n"] for b in every["matches_per_user"]) == every["users"]
    assert sum(t["n"] for t in every["tiers"]) == every["matches"]
    assert every["top_lenders"] and "user_id" not in json.dumps(every)  # aggregates only
    one_job = repository.analytics(db, db.job_id)
    assert 0 < one_job["users"] <= every["users"]
    assert repository.analytics(db, uuid.uuid4())["users"] == 0


def test_sweeper_and_claim_retry_failed_jobs_a_bounded_number_of_times(db):
    """DF6: a transient failure is retried (after a 10 min backoff), at most 3 times."""
    job = uuid.uuid4()
    db.execute(
        "INSERT INTO upload_jobs (job_id, s3_key, status, completed_at) "
        "VALUES (%s, %s, 'COMPLETED', now())",
        (job, f"raw/{job}.csv"),
    )

    def swept() -> set:
        return {r[1] for r in db.execute(sql("sweeper.sql")).fetchall()}

    def claim() -> list:
        return db.execute(sql("claim.sql"), {"p1": "upload", "p2": str(job), "p3": ""}).fetchall()

    def fail_run(minutes_ago: int) -> None:
        """What B's "Mark job failed" does, with the failure dated `minutes_ago`."""
        db.execute(
            "UPDATE pipeline_runs SET status = 'failed', "
            "finished_at = now() - make_interval(mins => %s) "
            "WHERE job_id = %s AND status = 'running'",
            (minutes_ago, job),
        )
        db.execute("UPDATE upload_jobs SET match_status = 'FAILED' WHERE job_id = %s", (job,))

    def age_failures() -> None:
        db.execute(
            "UPDATE pipeline_runs SET finished_at = now() - interval '11 minutes' "
            "WHERE job_id = %s",
            (job,),
        )

    assert str(job) in swept()  # never matched: picked up
    assert len(claim()) == 1
    assert claim() == []  # atomic: the second claim gets nothing
    fail_run(minutes_ago=1)
    assert str(job) not in swept()  # backoff: failed a minute ago
    age_failures()
    assert str(job) in swept()  # 1 failure, 10+ min ago: retried
    for _ in range(2):  # second and third failures
        assert len(claim()) == 1
        fail_run(minutes_ago=11)
    failed = db.execute(
        "SELECT count(*) FROM pipeline_runs WHERE job_id = %s AND status = 'failed'", (job,)
    ).fetchone()[0]
    assert failed == 3
    assert str(job) not in swept()  # out of retries: stays FAILED for a human
    assert claim() == []


def test_product_mode_never_supersedes_a_user_who_was_not_classified(db):
    """DF11: a user created between Stage 1 and Stage 3 keeps their matches untouched."""
    product_id = db.execute(
        "SELECT product_id FROM matches WHERE status = 'active' "
        "GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
    ).fetchone()[0]
    run = str(
        db.execute(
            "INSERT INTO pipeline_runs (mode, scope_product_ids) "
            "VALUES ('products', ARRAY[%s]::uuid[]) RETURNING run_id",
            (product_id,),
        ).fetchone()[0]
    )
    run_sql(db, "stage1_classes.sql", run, PROMPT_VERSION)
    # A user arrives (or changes) after Stage 1, with an outlier profile no class covers.
    late = uuid.uuid4()
    db.execute(
        "INSERT INTO users (user_id, email, monthly_income, credit_score, employment_status, age, "
        "upload_job_id) VALUES (%s, 'late@example.org', 99999999, 300, 'business', 99, %s)",
        (late, db.job_id),
    )
    db.execute(
        "INSERT INTO matches (user_id, product_id, job_id, match_run_id, tier, stage_decided, "
        "fit_score) VALUES (%s, %s, %s, %s, 'eligible', 'sql', 50)",
        (late, product_id, db.job_id, run),
    )
    stage3(db, run)
    status = db.execute(
        "SELECT status FROM matches WHERE user_id = %s AND product_id = %s", (late, product_id)
    ).fetchone()[0]
    assert status == "active"


def test_awaiting_notification_only_returns_users_with_unnotified_matches(db):
    from loan_engine.api import repository

    pending = db.execute(
        "SELECT user_id FROM matches WHERE status = 'active' AND notified_at IS NULL LIMIT 1"
    ).fetchone()[0]
    db.execute("UPDATE matches SET notified_at = now() WHERE user_id = %s", (pending,))
    assert repository.awaiting_notification(db, [pending, uuid.uuid4()]) == set()
    db.execute("UPDATE matches SET notified_at = NULL WHERE user_id = %s", (pending,))
    assert repository.awaiting_notification(db, [pending]) == {pending}
    assert repository.csv_uploads_last_24h(db) >= 0


def test_data_reset_runs_as_app_ingest_and_keeps_history(db):
    """Migration 006 + R__grants: the api role can delete users and the cascade takes their
    matches, emails and links; pipeline_runs, products and the job rows stay."""
    from loan_engine.api import repository

    db.execute(
        "DO $$ BEGIN"
        " IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_ingest') THEN"
        " CREATE ROLE app_ingest; END IF;"
        " IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n_workflows') THEN"
        " CREATE ROLE n8n_workflows; END IF; END $$"
    )
    db.execute((ROOT / "sql" / "R__grants.sql").read_text())
    product_id = db.execute("SELECT product_id FROM loan_products LIMIT 1").fetchone()[0]

    def upload(source: str, n: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
        """A small loaded + matched + emailed upload of n users."""
        job = uuid.uuid4()
        db.execute(
            "INSERT INTO upload_jobs (job_id, s3_key, status, match_status, source)"
            " VALUES (%s, %s, 'COMPLETED', 'DONE', %s)",
            (job, f"raw/{job}.csv", source),
        )
        run = db.execute(
            "INSERT INTO pipeline_runs (mode, job_id, status) VALUES ('upload', %s, 'done')"
            " RETURNING run_id",
            (job,),
        ).fetchone()[0]
        users = [uuid.uuid4() for _ in range(n)]
        for u in users:
            db.execute(
                "INSERT INTO users (user_id, email, monthly_income, credit_score,"
                " employment_status, age, upload_job_id)"
                " VALUES (%s, 'reset@example.org', 50000, 750, 'salaried', 30, %s)",
                (u, job),
            )
            db.execute(
                "INSERT INTO matches (user_id, product_id, job_id, match_run_id, tier,"
                " stage_decided, fit_score) VALUES (%s, %s, %s, %s, 'eligible', 'sql', 50)",
                (u, product_id, job, run),
            )
            db.execute(
                "INSERT INTO notifications (user_id, alias_email, job_id, run_id, status)"
                " VALUES (%s, 'x+1@gmail.com', %s, %s, 'sent')",
                (u, job, run),
            )
        return job, users

    csv_job, csv_users = upload("csv", 3)
    check_job, (check_user,) = upload("instant_check", 1)
    _, (other_check,) = upload("instant_check", 1)
    repository.upsert_account(db, "sub-reset", "reset@example.org")
    assert repository.claim_profile(db, "sub-reset", check_user) == "saved"
    assert repository.claim_profile(db, "sub-reset", csv_users[0]) == "saved"

    def count(table: str, users: list[uuid.UUID]) -> int:
        return db.execute(
            f"SELECT count(*) FROM {table} WHERE user_id = ANY(%s)", (users,)
        ).fetchone()[0]

    db.execute("SET ROLE app_ingest")
    try:
        # A busy job is refused; a dashboard link cannot delete bulk-upload data.
        db.execute("RESET ROLE")
        db.execute("UPDATE upload_jobs SET match_status = 'RUNNING' WHERE job_id = %s", (csv_job,))
        db.execute("SET ROLE app_ingest")
        with pytest.raises(repository.JobBusyError):
            repository.purge_upload(db, csv_job)
        db.execute("RESET ROLE")
        db.execute("UPDATE upload_jobs SET match_status = 'DONE' WHERE job_id = %s", (csv_job,))
        db.execute("SET ROLE app_ingest")
        assert repository.delete_check(db, csv_users[1]) == "csv_user"
        # Just matched: Workflow C may still be emailing this user, so the delete waits.
        db.execute("RESET ROLE")
        db.execute("UPDATE upload_jobs SET matched_at = now() WHERE job_id = %s", (check_job,))
        db.execute("SET ROLE app_ingest")
        assert repository.delete_check(db, check_user) == "busy"
        db.execute("RESET ROLE")
        db.execute(
            "UPDATE upload_jobs SET matched_at = now() - interval '1 hour' WHERE job_id = %s",
            (check_job,),
        )
        db.execute("SET ROLE app_ingest")

        # Start fresh: the instant check is deleted, the saved bulk profile only unlinked.
        assert repository.clear_account_profiles(db, "sub-reset") == {
            "deleted_checks": 1,
            "unlinked": 1,
        }
        assert count("users", [check_user]) == 0 and count("users", [csv_users[0]]) == 1
        assert repository.upsert_account(db, "sub-reset", "reset@example.org")["daily_picks"]

        assert repository.delete_check(db, other_check) == "deleted"
        assert repository.purge_upload(db, csv_job) == 3
        assert repository.purge_upload(db, uuid.uuid4()) is None
    finally:
        db.execute("RESET ROLE")

    gone = [*csv_users, check_user, other_check]
    assert count("users", gone) == count("matches", gone) == count("notifications", gone) == 0
    assert db.execute(
        "SELECT purged_at IS NOT NULL FROM upload_jobs WHERE job_id = %s", (csv_job,)
    ).fetchone()[0]
    # History stays: the runs and job rows are still there for the Treasure Hunt evidence.
    assert (
        db.execute(
            "SELECT count(*) FROM pipeline_runs WHERE job_id = ANY(%s)", ([csv_job, check_job],)
        ).fetchone()[0]
        == 2
    )
    runs = repository.ops_runs(db)
    assert any(r["job_id"] == csv_job and r["purged"] for r in runs)
    # Newer small runs never hide the full-file reference run.
    refs = [r for r in runs if r["reference"]]
    assert len(refs) == 1 and (refs[0]["users_in"] or 0) == max(
        r["users_in"] or 0 for r in runs if r["mode"] == "upload" and r["status"] == "done"
    )
    # The upload list shows the cleared upload as its own record, emptied but kept.
    records = {r["job_id"]: r for r in repository.list_uploads(db)}
    assert records[csv_job]["users_now"] == 0 and records[csv_job]["purged_at"] is not None
    assert records[csv_job]["emails_sent"] == 0  # its email rows went with the users
    assert check_job not in records  # instant checks are not bulk uploads
