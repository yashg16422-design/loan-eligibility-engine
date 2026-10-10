"""Shared setup for the matching integration tests: schema, production ingest, product snapshot.

Moved out of test_matching_db.py unchanged so the golden-master test builds exactly the same
database; only the CSV differs (the golden test pins the synthetic file).
"""

from __future__ import annotations

import io
import json
import os
import re
import uuid
from pathlib import Path

import psycopg

from loan_engine.common.secrets import DbCredentials
from loan_engine.common.validation import DEFAULT_RULES
from loan_engine.ingest import handler as ingest
from loan_engine.ingest.events import UploadRef

PORT = os.environ.get("PG_TEST_PORT")
ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "tests" / "fixtures" / "products_snapshot.json"
CREDS = DbCredentials("postgres", os.environ.get("PG_TEST_PASSWORD", "localtest"))
PROMPT_VERSION = "test_v1"

PRODUCT_COLUMNS = [
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


def sql(name: str) -> str:
    """Load an n8n query and convert its $1-style params to psycopg's %(pN)s style."""
    text = (ROOT / "sql" / "matching" / name).read_text()
    return re.sub(r"\$(\d+)", r"%(p\1)s", text.replace("%", "%%"))


def run_sql(db: psycopg.Connection, name: str, *params: object) -> dict:
    cur = db.execute(sql(name), {f"p{i + 1}": p for i, p in enumerate(params)})
    names = [c.name for c in cur.description or []]
    return dict(zip(names, cur.fetchone() or (), strict=True))


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host="localhost",
        port=int(PORT or 0),
        dbname="app",
        user=CREDS.username,
        password=CREDS.password,
        autocommit=True,
    )


def fresh_schema(conn: psycopg.Connection) -> None:
    """Drop everything and apply every numbered migration, in order."""
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    for migration in sorted((ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql")):
        conn.execute(migration.read_text())


def ingest_csv(
    conn: psycopg.Connection, csv_bytes: bytes, streaming: bool | None = None
) -> uuid.UUID:
    """Create an upload job and run the PRODUCTION ingest code on `csv_bytes`.

    `streaming` picks the ingest path; None = INGEST_STREAMING from the environment, so the
    whole integration suite can run on either path (CI runs both)."""
    if streaming is None:
        streaming = os.environ.get("INGEST_STREAMING", "false").lower() == "true"
    job_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO upload_jobs (job_id, s3_key) VALUES (%s, %s)", (job_id, f"raw/{job_id}.csv")
    )

    class S3:
        def get_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
            return {"Body": io.BytesIO(csv_bytes)}

    deps = ingest.Dependencies(
        "localhost", "x", int(PORT or 0), DEFAULT_RULES, ingest.NoopNotifier(), S3(), streaming
    )
    ingest.cached_db_credentials = lambda arn: CREDS  # type: ignore[assignment]
    ingest.process_upload(UploadRef("b", f"raw/{job_id}.csv", job_id), 1, deps)
    return job_id


def load_products_and_rules(conn: psycopg.Connection) -> None:
    """The live product snapshot plus compiled residual rules for three real criteria texts."""
    insert = (
        f"INSERT INTO loan_products ({', '.join(PRODUCT_COLUMNS)}) "
        f"VALUES ({', '.join(f'%({c})s' for c in PRODUCT_COLUMNS)})"
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


def stage3(db: psycopg.Connection, run_id: str) -> dict:
    """What Workflow B does after Stage 1: refresh statistics, then expand + diff."""
    db.execute((ROOT / "sql" / "matching" / "refresh_stats.sql").read_text())
    return run_sql(db, "stage3_expand.sql", run_id)
