"""All SQL used by the ingest Lambda (the repository seam).

The handler calls these functions and never writes SQL itself, so a table or upsert
change is a one-file edit. Every function takes an open connection and expects the
caller to own the transaction boundaries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg

from loan_engine.common.validation import Reject, UserRow

_USER_COLUMNS = (
    "user_id",
    "name",
    "email",
    "monthly_income",
    "credit_score",
    "employment_status",
    "age",
)


@dataclass(frozen=True, slots=True)
class LoadCounts:
    """What the upsert did. `unchanged` = valid rows identical to what was stored."""

    inserted: int
    updated: int
    unchanged: int


def bump_attempts(conn: psycopg.Connection, job_id: uuid.UUID) -> None:
    """Count an ingest attempt, only while the job is still waiting.

    Separate short transaction (PLAN.md §5.3 step 3): it must survive even if the main
    transaction rolls back, and duplicate deliveries for finished jobs don't inflate it.
    """
    conn.execute(
        "UPDATE upload_jobs SET attempts = attempts + 1"
        " WHERE job_id = %s AND status = 'AWAITING_UPLOAD'",
        (job_id,),
    )


def job_account(conn: psycopg.Connection, job_id: uuid.UUID) -> str | None:
    """The merchant account that owns an upload (None: an instant check or an older upload)."""
    row = conn.execute("SELECT account_id FROM upload_jobs WHERE job_id = %s", (job_id,)).fetchone()
    return row[0] if row else None


def claim_job(conn: psycopg.Connection, job_id: uuid.UUID) -> bool:
    """Lock the job for this transaction and mark it PROCESSING.

    SKIP LOCKED: a concurrent duplicate delivery gets False immediately instead of
    waiting, and treats it as "someone else has it". False also covers jobs that are
    already COMPLETED/FAILED or don't exist (duplicate or stray events).
    """
    row = conn.execute(
        "SELECT 1 FROM upload_jobs WHERE job_id = %s AND status = 'AWAITING_UPLOAD'"
        " FOR UPDATE SKIP LOCKED",
        (job_id,),
    ).fetchone()
    if row is None:
        return False
    conn.execute("UPDATE upload_jobs SET status = 'PROCESSING' WHERE job_id = %s", (job_id,))
    return True


def load_users(conn: psycopg.Connection, job_id: uuid.UUID, users: list[UserRow]) -> LoadCounts:
    """COPY valid rows into a private TEMP table, then upsert into `users`.

    - TEMP ... ON COMMIT DROP: private to this transaction, so concurrent jobs can't
      see or clobber each other's staging rows (never a shared staging table).
    - COPY: one streamed round-trip instead of 10,000 INSERTs.
    - The upsert only touches rows whose values actually changed (IS DISTINCT FROM),
      and only those get upload_job_id = this job, so Workflow B re-matches exactly
      the new or changed users.
    - `xmax = 0` is true only for freshly inserted rows: a standard Postgres trick to
      tell inserts from updates in one statement.
    """
    conn.execute(
        "CREATE TEMP TABLE staging_users ("
        " user_id uuid, name text, email text, monthly_income int,"
        " credit_score int, employment_status text, age int) ON COMMIT DROP"
    )
    with conn.cursor() as cur:
        copy_sql = f"COPY staging_users ({', '.join(_USER_COLUMNS)}) FROM STDIN"
        with cur.copy(copy_sql) as copy:
            for u in users:
                copy.write_row(
                    (
                        u.user_id,
                        u.name,
                        u.email,
                        u.monthly_income,
                        u.credit_score,
                        u.employment_status.value,
                        u.age,
                    )
                )

    inserted, updated = conn.execute(
        """
        WITH upserted AS (
            INSERT INTO users AS u
                (user_id, name, email, monthly_income, credit_score,
                 employment_status, age, upload_job_id)
            SELECT user_id, name, email, monthly_income, credit_score,
                   employment_status, age, %(job_id)s
            FROM staging_users
            ON CONFLICT (user_id) DO UPDATE SET
                name = EXCLUDED.name,
                email = EXCLUDED.email,
                monthly_income = EXCLUDED.monthly_income,
                credit_score = EXCLUDED.credit_score,
                employment_status = EXCLUDED.employment_status,
                age = EXCLUDED.age,
                upload_job_id = EXCLUDED.upload_job_id,
                updated_at = now()
            WHERE (u.name, u.email, u.monthly_income, u.credit_score,
                   u.employment_status, u.age)
                  IS DISTINCT FROM
                  (EXCLUDED.name, EXCLUDED.email, EXCLUDED.monthly_income,
                   EXCLUDED.credit_score, EXCLUDED.employment_status, EXCLUDED.age)
            RETURNING (xmax = 0) AS was_inserted
        )
        SELECT count(*) FILTER (WHERE was_inserted),
               count(*) FILTER (WHERE NOT was_inserted)
        FROM upserted
        """,
        {"job_id": job_id},
    ).fetchone() or (0, 0)
    return LoadCounts(inserted=inserted, updated=updated, unchanged=len(users) - inserted - updated)


def save_rejects(conn: psycopg.Connection, job_id: uuid.UUID, rejects: list[Reject]) -> None:
    """Store every rejected row (the UI shows the first 20)."""
    with (
        conn.cursor() as cur,
        cur.copy("COPY upload_rejects (job_id, row_number, raw_line, reason) FROM STDIN") as copy,
    ):
        for r in rejects:
            copy.write_row((job_id, r.row_number, r.raw_line, r.reason))


def complete_job(
    conn: psycopg.Connection,
    job_id: uuid.UUID,
    *,
    total_rows: int,
    counts: LoadCounts,
    rejected: int,
) -> None:
    """Mark the job COMPLETED with its counts (same transaction as the data)."""
    conn.execute(
        """
        UPDATE upload_jobs
        SET status = 'COMPLETED', completed_at = now(), error = NULL,
            total_rows = %s, inserted = %s, updated = %s, unchanged = %s, rejected = %s
        WHERE job_id = %s
        """,
        (total_rows, counts.inserted, counts.updated, counts.unchanged, rejected, job_id),
    )


def fail_job(conn: psycopg.Connection, job_id: uuid.UUID, error: str) -> None:
    """Mark a job FAILED, unless it already finished (never overwrite COMPLETED)."""
    conn.execute(
        "UPDATE upload_jobs SET status = 'FAILED', error = %s, completed_at = now()"
        " WHERE job_id = %s AND status IN ('AWAITING_UPLOAD', 'PROCESSING')",
        (error[:2000], job_id),
    )
