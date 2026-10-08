"""All SQL used by the api Lambda (runs as the least-privilege `app_ingest` role)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

REJECTS_SHOWN = 20


def create_job(
    conn: psycopg.Connection, job_id: uuid.UUID, s3_key: str, filename: str | None
) -> None:
    """Register the upload ticket before the browser gets permission to upload."""
    conn.execute(
        "INSERT INTO upload_jobs (job_id, s3_key, original_filename) VALUES (%s, %s, %s)",
        (job_id, s3_key, filename),
    )


def get_job_progress(conn: psycopg.Connection, job_id: uuid.UUID) -> dict[str, Any] | None:
    """Everything the UI tracker shows for one job, or None if the job doesn't exist.

    `db_now` comes from Postgres so EXPIRED is computed against the same clock that
    wrote `created_at` (no Lambda/DB clock skew).
    """
    with conn.cursor(row_factory=dict_row) as cur:
        job = cur.execute(
            """
            SELECT job_id, original_filename, status, attempts, total_rows, inserted,
                   updated, unchanged, rejected, error, created_at, completed_at,
                   match_status, matched_at, now() AS db_now
            FROM upload_jobs WHERE job_id = %s
            """,
            (job_id,),
        ).fetchone()
        if job is None:
            return None

        rejects = cur.execute(
            "SELECT row_number, reason, raw_line FROM upload_rejects"
            " WHERE job_id = %s ORDER BY row_number LIMIT %s",
            (job_id, REJECTS_SHOWN),
        ).fetchall()

        # The latest matching run for this job: the Treasure Hunt funnel.
        match_run = cur.execute(
            """
            SELECT status, users_in, products_in, naive_pairs, pairs_after_sql, classes,
                   class_product_pairs, llm_candidates, llm_cache_hits, llm_calls,
                   matches_new, emails_sent, emails_skipped_demo, emails_failed
            FROM pipeline_runs WHERE job_id = %s ORDER BY started_at DESC LIMIT 1
            """,
            (job_id,),
        ).fetchone()

        notified = {
            row["status"]: row["n"]
            for row in cur.execute(
                "SELECT status, count(*) AS n FROM notifications WHERE job_id = %s GROUP BY status",
                (job_id,),
            )
        }

    return {"job": job, "rejects": rejects, "match_run": match_run, "notifications": notified}
