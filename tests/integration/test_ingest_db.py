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
    for migration in sorted((ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql")):  # the real schema
        conn.execute(migration.read_text())
    yield conn
    conn.close()


# Every ingest test runs on both paths: the original in-memory one and the constant-memory
# streaming one (INGEST_STREAMING). They must behave identically.
@pytest.fixture(params=[False, True], ids=["in-memory", "streaming"])
def env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, db: psycopg.Connection):
    s3, notifier = FakeS3(), RecordingNotifier()
    deps = ingest.Dependencies(
        db_host="localhost",
        db_secret_arn="x",
        db_port=int(PORT or 0),
        rules=DEFAULT_RULES,
        notifier=notifier,
        s3=s3,
        streaming=request.param,
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
        # Valid header and first rows, then bytes that are not UTF-8: the streaming path has
        # already COPYed rows by then; its savepoint must roll them back and still fail cleanly.
        (
            b"user_id,name,email,monthly_income,credit_score,employment_status,age\n"
            + b"33f22eb9-6487-4c15-8e43-5ff59be31a9b,A,a@example.com,48000,742,Salaried,29\n" * 3000
            + b"\xff\xfe broken\n",
            "not UTF-8",
        ),
    ],
)
def test_bad_file_fails_immediately_without_retry(db, env, body, error_part):
    deps, s3, notifier = env
    upload = new_job(db, s3, body)
    assert ingest.process_upload(upload, 1, deps) is ingest.Outcome.BAD_FILE
    j = job(db, upload.job_id)
    assert j["status"] == "FAILED" and error_part in j["error"]
    assert notifier.notified == []
    # Nothing from a bad file is kept.
    assert db.execute(
        "SELECT count(*) FROM users WHERE upload_job_id = %s", (upload.job_id,)
    ).fetchone() == (0,)


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


def test_each_account_starts_fresh_with_the_same_file(db, env):
    """The same CSV uploaded by two merchant accounts loads twice (fresh customers for each);
    the same account uploading it again is still idempotent."""
    deps, s3, _ = env
    body = f"{HEADER}{U1},A,a@x.com,50000,700,Salaried,30\n{U2},B,b@x.com,60000,720,Salaried,35\n"
    for account in ("acct-a", "acct-b"):
        db.execute(
            "INSERT INTO accounts (account_id, email) VALUES (%s, %s)",
            (account, f"{account}@x.org"),
        )

    def owned_upload(account: str) -> uuid.UUID:
        upload = new_job(db, s3, body)
        db.execute(
            "UPDATE upload_jobs SET account_id = %s WHERE job_id = %s", (account, upload.job_id)
        )
        assert ingest.process_upload(upload, 1, deps) == ingest.Outcome.COMPLETED
        return upload.job_id

    first, second, again = owned_upload("acct-a"), owned_upload("acct-b"), owned_upload("acct-a")
    assert (job(db, first)["inserted"], job(db, second)["inserted"]) == (2, 2)  # both fresh
    assert (job(db, again)["inserted"], job(db, again)["unchanged"]) == (0, 2)  # idempotent
    assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 4


def test_streaming_ingest_memory_does_not_grow_with_the_file(db, monkeypatch, tmp_path):
    """100,000 rows: the streaming path's peak Python memory stays small and flat, while the
    in-memory path holds every row (measured with tracemalloc around process_upload)."""
    import tracemalloc

    from tests.synthetic_users import synthetic_users_csv

    path = tmp_path / "big.csv"
    path.write_bytes(synthetic_users_csv(rows=100_000, seed=7))

    class FileS3:  # the body streams from disk, like S3's StreamingBody
        def get_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
            return {"Body": path.open("rb")}

    monkeypatch.setattr(ingest, "cached_db_credentials", lambda arn: CREDS)
    peaks = {}
    for streaming in (False, True):
        db.execute("TRUNCATE users CASCADE")
        upload = new_job(db, FakeS3(), b"")
        deps = ingest.Dependencies(
            "localhost",
            "x",
            int(PORT or 0),
            DEFAULT_RULES,
            RecordingNotifier(),
            FileS3(),
            streaming,
        )
        tracemalloc.start()
        assert ingest.process_upload(upload, 1, deps) is ingest.Outcome.COMPLETED
        peaks[streaming] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        assert job(db, upload.job_id)["inserted"] == 100_000
    print(f"\nPEAK MB in-memory={peaks[False] / 1e6:.1f} streaming={peaks[True] / 1e6:.1f}")
    assert peaks[True] < 16 * 1024 * 1024  # flat: independent of the row count
    assert peaks[True] * 4 < peaks[False]


# ---------------------------------------------------------------- concurrency (N7)


def _parallel(*calls):
    """Run the calls at the same moment on separate threads (each opens its own connection)."""
    import threading

    barrier = threading.Barrier(len(calls))
    results: list[object] = [None] * len(calls)

    def run(i, fn):
        barrier.wait()
        try:
            results[i] = fn()
        except Exception as err:
            results[i] = err

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_the_same_job_delivered_twice_at_once_loads_once(db, env):
    deps, s3, notifier = env
    upload = new_job(db, s3, users_csv_bytes())
    results = _parallel(
        lambda: ingest.process_upload(upload, 1, deps),
        lambda: ingest.process_upload(upload, 1, deps),
    )
    assert sorted(r.value for r in results) == sorted(
        [ingest.Outcome.COMPLETED.value, ingest.Outcome.DUPLICATE.value]
    )
    j = job(db, upload.job_id)
    assert (j["status"], j["total_rows"]) == ("COMPLETED", 10_000)
    assert notifier.notified == [upload.job_id]  # n8n is told exactly once


def test_two_uploads_sharing_users_at_once_both_complete(db, env):
    """Overlapping user ids in two files loaded concurrently: rows are locked in user_id
    order, so neither deadlocks; the final rows are one of the two files' versions."""
    deps, s3, _ = env
    db.execute("TRUNCATE users CASCADE")
    head = "user_id,name,email,monthly_income,credit_score,employment_status,age\n"
    ids = [str(uuid.uuid4()) for _ in range(3000)]
    file_a = head + "".join(f"{u},A,a@example.com,40000,700,Salaried,30\n" for u in ids)
    file_b = head + "".join(f"{u},B,b@example.com,50000,710,Salaried,31\n" for u in reversed(ids))
    a, b = new_job(db, s3, file_a), new_job(db, s3, file_b)
    for _ in range(5):  # repeat: a lock-order bug shows up as a deadlock in some runs
        results = _parallel(
            lambda: ingest.process_upload(a, 1, deps), lambda: ingest.process_upload(b, 1, deps)
        )
        assert all(r is ingest.Outcome.COMPLETED for r in results), results
        rows = db.execute("SELECT count(*), count(DISTINCT name) FROM users").fetchone()
        assert rows[0] == 3000 and rows[1] in (1, 2)
        for upload in (a, b):  # reset both jobs and run them again
            db.execute(
                "UPDATE upload_jobs SET status = 'AWAITING_UPLOAD' WHERE job_id = %s",
                (upload.job_id,),
            )
            db.execute("DELETE FROM upload_rejects WHERE job_id = %s", (upload.job_id,))


def test_webhook_and_sweeper_claiming_the_same_job_at_once_start_one_run(db, env):
    """Workflow B's claim (sql/matching/claim.sql) raced by two callers: exactly one run."""
    from tests.integration.matching_setup import connect, sql

    deps, s3, _ = env
    upload = new_job(db, s3, users_csv_bytes())
    assert ingest.process_upload(upload, 1, deps) is ingest.Outcome.COMPLETED

    def claim():
        with connect() as conn:
            params = {"p1": "upload", "p2": str(upload.job_id), "p3": ""}
            return conn.execute(sql("claim.sql"), params).fetchall()

    results = _parallel(claim, claim)
    assert sorted(len(r) for r in results) == [0, 1]
    runs = db.execute(
        "SELECT count(*) FROM pipeline_runs WHERE job_id = %s AND status = 'running'",
        (upload.job_id,),
    ).fetchone()[0]
    assert runs == 1
