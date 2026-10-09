"""Integration tests: the real ingest flow against a real Postgres 16.

Runs only when PG_TEST_PORT is set (a throwaway local container with SSL), e.g.:

    docker run -d --rm --name ingest-test -e POSTGRES_PASSWORD=localtest \
      -e POSTGRES_DB=app -p 55432:5432 postgres:16 -c ssl=on \
      -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem \
      -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key
    PG_TEST_PORT=55432 .venv/bin/pytest tests/integration

S3 is replaced by an in-memory fake; everything else (transactions, COPY, upsert,
locking, failure policy) is the production code path.
"""

from __future__ import annotations

import dataclasses
import io
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest

from loan_engine.common.notifier import NoopNotifier
from loan_engine.common.secrets import DbCredentials
from loan_engine.common.validation import DEFAULT_RULES
from loan_engine.ingest import handler as ingest
from loan_engine.ingest.events import UploadRef
from tests.synthetic_users import users_csv_bytes

PORT = os.environ.get("PG_TEST_PORT")
pytestmark = pytest.mark.skipif(not PORT, reason="set PG_TEST_PORT to run DB integration tests")

ROOT = Path(__file__).resolve().parents[2]
CREDS = DbCredentials("postgres", os.environ.get("PG_TEST_PASSWORD", "localtest"))
HEADER = "user_id,name,email,monthly_income,credit_score,employment_status,age\n"
U1, U2 = "b35de23e-755f-4c6a-81d8-f7dd99ce53ef", "77fce4da-b901-4b27-b1bb-01989567b98b"


class FakeS3:
    """Holds object bodies in memory; mimics get_object()['Body']."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise KeyError(f"NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}


class RecordingNotifier(NoopNotifier):
    def __init__(self) -> None:
        self.notified: list[uuid.UUID] = []

    def notify_job_completed(self, job_id: uuid.UUID) -> bool:
        self.notified.append(job_id)
        return True


@pytest.fixture
def db() -> psycopg.Connection:
    """A fresh schema for every test."""
    conn = psycopg.connect(
        host="localhost",
        port=int(PORT or 0),
        dbname="app",
        user=CREDS.username,
        password=CREDS.password,
        autocommit=True,
    )
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    conn.execute((ROOT / "sql" / "001_schema.sql").read_text())
    yield conn
    conn.close()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, db: psycopg.Connection):
    s3, notifier = FakeS3(), RecordingNotifier()
    deps = ingest.Dependencies(
        db_host="localhost",
        db_secret_arn="x",
        db_port=int(PORT or 0),
        rules=DEFAULT_RULES,
        notifier=notifier,
        s3=s3,
    )
    monkeypatch.setattr(ingest, "cached_db_credentials", lambda arn: CREDS)
    return deps, s3, notifier


def new_job(db: psycopg.Connection, s3: FakeS3, body: str | bytes) -> UploadRef:
    """What the upload API + browser do: create the job row, then the S3 object."""
    job_id = uuid.uuid4()
    key = f"raw/{job_id}.csv"
    db.execute("INSERT INTO upload_jobs (job_id, s3_key) VALUES (%s, %s)", (job_id, key))
    s3.objects[key] = body.encode() if isinstance(body, str) else body
    return UploadRef(bucket="b", key=key, job_id=job_id)


def job(db: psycopg.Connection, job_id: uuid.UUID) -> dict[str, Any]:
    cur = db.execute(
        "SELECT status, attempts, total_rows, inserted, updated, unchanged, rejected, error"
        " FROM upload_jobs WHERE job_id = %s",
        (job_id,),
    )
    names = [c.name for c in cur.description or []]
    return dict(zip(names, cur.fetchone() or (), strict=True))


# ---------------------------------------------------------------- tests


def test_10k_users_csv_loads(db, env):
    """The real file locally; its synthetic twin in CI (tests/synthetic_users.py)."""
    deps, s3, notifier = env
    upload = new_job(db, s3, users_csv_bytes())

    assert ingest.process_upload(upload, 1, deps) is ingest.Outcome.COMPLETED

    j = job(db, upload.job_id)
    assert (j["status"], j["total_rows"], j["inserted"], j["rejected"]) == (
        "COMPLETED",
        10000,
        10000,
        0,
    )
    assert db.execute("SELECT count(*) FROM users").fetchone() == (10000,)
    assert notifier.notified == [upload.job_id]  # announced only after commit


def test_same_file_twice_is_idempotent(db, env):
    deps, s3, _ = env
    body = f"{HEADER}{U1},A,a@x.com,50000,700,Salaried,30\n{U2},B,b@x.com,60000,710,Business,40\n"
    first, second = new_job(db, s3, body), new_job(db, s3, body)
    ingest.process_upload(first, 1, deps)
    ingest.process_upload(second, 1, deps)

    j = job(db, second.job_id)
    assert (j["inserted"], j["updated"], j["unchanged"]) == (0, 0, 2)
    # Unchanged users keep the FIRST job id, so Workflow B won't re-match them.
    assert db.execute(
        "SELECT count(*) FROM users WHERE upload_job_id = %s", (second.job_id,)
    ).fetchone() == (0,)


def test_changed_user_is_updated_and_retagged(db, env):
    deps, s3, _ = env
    ingest.process_upload(
        new_job(db, s3, f"{HEADER}{U1},A,a@x.com,50000,700,Salaried,30\n"), 1, deps
    )
    second = new_job(db, s3, f"{HEADER}{U1},A,a@x.com,90000,700,Salaried,30\n")
    ingest.process_upload(second, 1, deps)

    j = job(db, second.job_id)
    assert (j["inserted"], j["updated"], j["unchanged"]) == (0, 1, 0)
    assert db.execute("SELECT monthly_income, upload_job_id FROM users").fetchone() == (
        90000,
        second.job_id,
    )


def test_duplicate_delivery_is_ignored(db, env):
    deps, s3, notifier = env
    upload = new_job(db, s3, f"{HEADER}{U1},A,a@x.com,50000,700,Salaried,30\n")
    assert ingest.process_upload(upload, 1, deps) is ingest.Outcome.COMPLETED
    assert ingest.process_upload(upload, 1, deps) is ingest.Outcome.DUPLICATE
    assert job(db, upload.job_id)["attempts"] == 1  # finished jobs don't count retries
    assert notifier.notified == [upload.job_id]  # announced once


def test_rejects_are_stored(db, env):
    deps, s3, _ = env
    body = f"{HEADER}{U1},A,a@x.com,50000,700,Salaried,30\nnot-a-uuid,B,b@x.com,1,700,Salaried,30\n"
    upload = new_job(db, s3, body)
    ingest.process_upload(upload, 1, deps)
    assert job(db, upload.job_id)["rejected"] == 1
    assert db.execute("SELECT row_number, reason FROM upload_rejects").fetchall() == [
        (3, "invalid_user_id")
    ]


@pytest.mark.parametrize(
    ("body", "error_part"),
    [
        ("user_id,email\n", "missing required column"),
        (b"\xff\xfe not utf-8", "not UTF-8"),
    ],
)
def test_bad_file_fails_immediately_without_retry(db, env, body, error_part):
    deps, s3, notifier = env
    upload = new_job(db, s3, body)
    assert ingest.process_upload(upload, 1, deps) is ingest.Outcome.BAD_FILE
    j = job(db, upload.job_id)
    assert j["status"] == "FAILED" and error_part in j["error"]
    assert notifier.notified == []


def test_transient_error_retries_then_fails_on_last_delivery(db, env):
    deps, _, notifier = env
    s3 = FakeS3()  # job row exists but the object is "missing": a non-file error
    upload = new_job(db, s3, "x")
    s3.objects.clear()
    deps = dataclasses.replace(deps, s3=s3)

    for attempt in (1, 2):  # SQS will redeliver: the exception must propagate
        with pytest.raises(KeyError):
            ingest.process_upload(upload, attempt, deps)
        assert job(db, upload.job_id)["status"] == "AWAITING_UPLOAD"  # rolled back

    assert ingest.process_upload(upload, 3, deps) is ingest.Outcome.POISON
    j = job(db, upload.job_id)
    assert (j["status"], j["attempts"]) == ("FAILED", 3)
    assert "after 3 tries" in j["error"]
    assert notifier.notified == []


def test_api_progress_of_a_real_job_serializes_to_json(db, env):
    """Real DB rows (UUID, timestamptz, numeric) must survive the API's JSON encoding."""
    import json

    from loan_engine.api.repository import get_job_progress
    from loan_engine.api.status import to_json_safe

    deps, s3, _ = env
    body = f"{HEADER}{U1},A,a@x.com,50000,700,Salaried,30\nbad,B,b@x.com,1,700,Salaried,30\n"
    upload = new_job(db, s3, body)
    ingest.process_upload(upload, 1, deps)
    db.execute(
        "INSERT INTO pipeline_runs (mode, job_id, naive_pairs, llm_cost_usd_est)"
        " VALUES ('upload', %s, 20, 0.0012)",
        (upload.job_id,),
    )

    progress = get_job_progress(db, upload.job_id)
    decoded = json.loads(json.dumps(to_json_safe(progress)))
    assert decoded["job"]["job_id"] == str(upload.job_id)
    assert decoded["job"]["status"] == "COMPLETED"
    assert decoded["rejects"][0]["reason"] == "invalid_user_id"
    assert decoded["match_run"]["naive_pairs"] == 20
    assert get_job_progress(db, uuid.uuid4()) is None
