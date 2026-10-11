"""End to end through the real API: uploads, limits, Stop, deletes, kept charts and emails.

Every request goes through the Lambda entry point (Mangum + FastAPI + our routes) and the real
repository SQL on PostgreSQL, with a real 10,000-customer upload, its real matches and sent
emails. Only S3 signing is faked. Two errors reached the live stack because unit tests had
stubbed these steps (a UUID in the kept emails, a delete past the API's 28 s); this test runs
them for real.

Runs with PG_TEST_PORT set, like the other DB tests.
"""

from __future__ import annotations

import json
import time
import uuid

import psycopg
import pytest

from loan_engine.api import handler as api
from loan_engine.api import repository
from tests.integration.matching_setup import (
    CREDS,
    PORT,
    PROMPT_VERSION,
    connect,
    fresh_schema,
    ingest_csv,
    load_products_and_rules,
    run_sql,
    stage3,
)
from tests.synthetic_users import synthetic_users_csv, users_csv_bytes
from tests.unit.apigw import ADMIN, MERCHANT, invoke, signed_in_as

pytestmark = pytest.mark.skipif(not PORT, reason="set PG_TEST_PORT to run DB integration tests")

ANNA = {**MERCHANT, "sub": "anna-sub", "email": "anna@example.org"}
BEN = {**MERCHANT, "sub": "ben-sub", "email": "ben@example.org"}
CARA = {**MERCHANT, "sub": "cara-sub", "email": "cara@example.org"}


class FakeS3:
    def generate_presigned_post(self, **kw: object) -> dict:
        return {"url": "https://s3.example", "fields": {}}


@pytest.fixture(scope="module")
def stack():
    """A database with Anna's finished 10k upload: matched, 3 emails sent, emailing over."""
    conn = connect()
    fresh_schema(conn)
    load_products_and_rules(conn)
    job = ingest_csv(conn, users_csv_bytes())
    anna = repository.upsert_account(conn, ANNA["sub"], ANNA["email"])["account_id"]
    conn.execute("UPDATE upload_jobs SET account_id = %s WHERE job_id = %s", (anna, job))
    run = str(
        conn.execute(
            "INSERT INTO pipeline_runs (mode, job_id) VALUES ('upload', %s) RETURNING run_id",
            (job,),
        ).fetchone()[0]
    )
    run_sql(conn, "stage1_classes.sql", run, PROMPT_VERSION)
    stage3(conn, run)
    conn.execute(
        "INSERT INTO notifications (user_id, alias_email, job_id, run_id, status)"
        " SELECT DISTINCT user_id, 'owner+one@gmail.com', %s, %s::uuid, 'sent' FROM matches"
        " WHERE status = 'active' LIMIT 3",
        (job, run),
    )
    conn.execute(
        "UPDATE pipeline_runs SET status = 'done', finished_at = now(), emails_sent = 3"
        " WHERE run_id = %s",
        (run,),
    )
    conn.execute(
        "UPDATE upload_jobs SET match_status = 'DONE',"
        " matched_at = now() - interval '10 minutes' WHERE job_id = %s",
        (job,),
    )
    yield conn, job
    conn.close()


@pytest.fixture(autouse=True)
def real_api(stack, monkeypatch):
    """The api's own db() and routes, connected to the test database."""
    deps = api.Dependencies(db_host="localhost", db_secret_arn="x", bucket="b", s3=FakeS3())
    monkeypatch.setattr(api, "dependencies", lambda: deps)
    monkeypatch.setattr(api, "cached_db_credentials", lambda arn: CREDS)
    monkeypatch.setattr(
        api,
        "connect",
        lambda host, dbname, creds, **kw: psycopg.connect(
            host="localhost",
            port=int(PORT or 0),
            dbname="app",
            user=creds.username,
            password=creds.password,
            autocommit=True,
        ),
    )
    monkeypatch.setattr(api, "_CONN", None)
    monkeypatch.setattr(api, "_ANALYTICS_CACHE", {})


def call(route: str, who: dict, job: uuid.UUID | None = None, query: dict | None = None):
    event: dict = {"routeKey": route, "requestContext": signed_in_as(who)}
    if job is not None:
        event["pathParameters"] = {"job_id": str(job)}
    if query:
        event["queryStringParameters"] = query
    if route.startswith("POST /uploads") and job is None:
        event["body"] = json.dumps({"filename": "users.csv"})
    started = time.monotonic()
    res = invoke(event)
    took = time.monotonic() - started
    assert took < api.DELETE_BUDGET_S + 5, f"{route} took {took:.1f}s"  # well inside 28 s
    return res["statusCode"], json.loads(res["body"])


def delete_until_done(route: str, who: dict, job: uuid.UUID | None = None, query=None) -> int:
    """What the console does: call again while the server reports customers left."""
    deleted = 0
    for _ in range(200):
        status, body = call(route, who, job, query)
        assert status == 200, body
        deleted += body["deleted_users"]
        if not body.get("remaining"):
            return deleted
    raise AssertionError("delete never finished")


def test_the_whole_upload_lifecycle(stack):
    conn, job = stack

    # 1. Anna already has an upload with customers: asked to delete it first (409, with what).
    status, body = call("POST /uploads", ANNA)
    assert status == 409
    assert body["blocking"]["stage"] == "stored" and body["blocking"]["customers"] == 10_000

    # 2. Ben can upload: two uploads may be in the database at once.
    status, ben = call("POST /uploads", BEN)
    assert status == 201

    # 3. Cara cannot: the database is full (503), and nothing about the others is revealed.
    status, body = call("POST /uploads", CARA)
    assert status == 503 and "blocking" not in body and "users.csv" not in body["error"]

    # 4. Anna deletes hers (the console's chunked loop); each call stays inside the API limit.
    charts_before = call("GET /uploads/{job_id}/analytics", ANNA, job)[1]
    assert delete_until_done("DELETE /uploads/{job_id}", ANNA, job) == 10_000
    assert repository.users_left(conn, job) == 0
    assert conn.execute(
        "SELECT count(*) FROM matches m JOIN users u USING (user_id) WHERE u.upload_job_id = %s",
        (job,),
    ).fetchone() == (0,)

    # 5. Her charts and example emails stay (the UUIDs in them once broke this live).
    status, charts = call("GET /uploads/{job_id}/analytics", ANNA, job)
    assert status == 200 and charts["data_deleted"] is True
    assert charts["users"] == charts_before["users"] == 10_000
    assert "email_previews" not in charts
    status, emails = call("GET /uploads/{job_id}/emails", ANNA, job)
    assert status == 200 and len(emails) == 3
    assert all(e["alias_email"] == "owner+one@gmail.com" for e in emails)
    rows = {u["job_id"]: u for u in call("GET /uploads", ANNA)[1]}
    assert rows[str(job)]["run_customers"] == 10_000 and rows[str(job)]["run_emails"] == 3
    # Another merchant cannot read them, or learn the upload exists.
    assert call("GET /uploads/{job_id}/emails", BEN, job)[0] == 404

    # 6. Anna can upload again; Cara still waits (Ben's and Anna's new tickets).
    status, _ = call("POST /uploads", ANNA)
    assert status == 201
    assert call("POST /uploads", CARA)[0] == 503

    # 7. Ben stops his upload before its file arrives: it is cancelled and frees a place.
    status, body = call("POST /uploads/{job_id}/cancel", BEN, uuid.UUID(ben["job_id"]))
    assert status == 200 and body["outcome"] == "cancelled"
    status, cara = call("POST /uploads", CARA)
    assert status == 201

    # 8. Stop, then the console's clean-up delete, works on a cancelled ticket too.
    assert call("POST /uploads/{job_id}/cancel", CARA, uuid.UUID(cara["job_id"]))[1] == {
        "job_id": cara["job_id"],
        "outcome": "cancelled",
    }
    assert delete_until_done("DELETE /uploads/{job_id}", CARA, uuid.UUID(cara["job_id"])) == 0

    # 9. Workspace reset and the admin's delete-all answer cleanly with nothing left to delete.
    assert delete_until_done("DELETE /uploads", ANNA) == 0
    boss = {**ADMIN, "sub": "boss-sub", "email": "boss@example.org"}
    assert delete_until_done("DELETE /uploads", boss, query={"scope": "all"}) == 0

    # 10. Signed out: no admin upload here, so no public dataset (never another merchant's).
    assert invoke({"routeKey": "GET /analytics"})["statusCode"] == 404


def test_reset_with_two_full_uploads_keeps_both_charts_within_the_limit(stack, monkeypatch):
    """Found live: delete-all on two 10k uploads passed 28 s (charts, then 15 s of deleting).
    Each call now shares one budget; charts are kept for every upload before it is deleted."""
    conn, _ = stack
    jobs = []
    for seed in (101, 202):  # two different files: different customers
        job = ingest_csv(conn, synthetic_users_csv(seed=seed))
        conn.execute(
            "UPDATE upload_jobs SET account_id = NULL, match_status = 'DONE',"
            " matched_at = now() - interval '10 minutes' WHERE job_id = %s",
            (job,),
        )
        jobs.append(job)
    # Slow charts: each takes most of the snapshot budget, as on the busy 1 GB database.
    real = api.cached_analytics

    def slow(c, j):
        time.sleep(api.SNAPSHOT_BUDGET_S * 0.6)
        return real(c, j)

    monkeypatch.setattr(api, "cached_analytics", slow)
    boss = {**ADMIN, "sub": "boss-sub", "email": "boss@example.org"}
    assert delete_until_done("DELETE /uploads", boss, query={"scope": "all"}) >= 10_000
    for job in jobs:
        assert repository.users_left(conn, job) == 0
        assert repository.analytics_snapshot(conn, job) is not None  # charts kept for each
