"""Workflow A's crawl-health check (sql/matching/crawl_health.sql) on a real Postgres."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.matching_setup import PORT, connect, fresh_schema, run_sql

pytestmark = pytest.mark.skipif(not PORT, reason="set PG_TEST_PORT to run DB integration tests")


@pytest.fixture(scope="module")
def db() -> psycopg.Connection:
    conn = connect()
    fresh_schema(conn)
    yield conn
    conn.close()


def crawl(db: psycopg.Connection, minutes_ago: int, pages: dict[str, tuple[int, int]]) -> str:
    """One crawl run: channel -> (usable pages, failed pages)."""
    run_id = str(uuid.uuid4())
    for channel, (usable, failed) in pages.items():
        for i in range(usable + failed):
            db.execute(
                "INSERT INTO crawl_runs (run_id, source_url, status, channel, started_at) "
                "VALUES (%s, %s, %s, %s, now() - make_interval(mins => %s))",
                (
                    run_id,
                    f"https://{channel}/{i}",
                    "ok" if i < usable else "failed",
                    channel,
                    minutes_ago,
                ),
            )
    return run_id


def test_healthy_run_does_not_alert(db):
    crawl(db, 300, {"direct": (40, 0), "bankbazaar": (20, 1)})
    healthy = crawl(db, 200, {"direct": (39, 1), "bankbazaar": (19, 2)})
    result = run_sql(db, "crawl_health.sql", healthy, 30)
    assert (result["degraded"], result["should_alert"]) == (False, False)
    assert result["summary"] == "all channels healthy"


def test_layout_change_alerts_once_per_day(db):
    # A redesign on BankBazaar: most of its pages now come back without an eligibility section.
    broken = crawl(db, 100, {"direct": (40, 0), "bankbazaar": (5, 16)})
    result = run_sql(db, "crawl_health.sql", broken, 30)
    assert (result["degraded"], result["should_alert"]) == (True, True)
    assert "bankbazaar: 5 usable pages (previous crawl 19)" in result["summary"]
    assert "direct" not in result["summary"]
    assert db.execute(
        "SELECT count(*) FROM workflow_errors WHERE workflow = 'A · crawl health'"
    ).fetchone() == (1,)
    # Still broken on the next crawl: recorded again, but no second email the same day.
    again = crawl(db, 10, {"direct": (40, 0), "bankbazaar": (0, 21)})
    result = run_sql(db, "crawl_health.sql", again, 30)
    assert (result["degraded"], result["should_alert"]) == (True, False)
    assert "bankbazaar: 0 usable pages" in result["summary"]
