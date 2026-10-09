"""All SQL used by the api Lambda (runs as the least-privilege `app_ingest` role)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

REJECTS_SHOWN = 20


def create_job(
    conn: psycopg.Connection,
    job_id: uuid.UUID,
    s3_key: str,
    filename: str | None,
    source: str = "csv",
) -> None:
    """Register the upload ticket before any file can reach S3 for it."""
    conn.execute(
        "INSERT INTO upload_jobs (job_id, s3_key, original_filename, source)"
        " VALUES (%s, %s, %s, %s)",
        (job_id, s3_key, filename, source),
    )


def instant_checks_last_24h(conn: psycopg.Connection) -> int:
    """How many instant checks ran in the last 24 h (the SES-quota guard)."""
    row = conn.execute(
        "SELECT count(*) FROM upload_jobs"
        " WHERE source = 'instant_check' AND created_at > now() - interval '24 hours'"
    ).fetchone()
    return int(row[0]) if row else 0


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


# ---------------------------------------------------------------- borrower dashboard

# Match/product fields the dashboard shows. Hard criteria are included so the UI can
# explain "why" and run the what-if simulator without a second request.
_PRODUCT_COLUMNS = """
    p.product_id, p.lender, p.lender_key, p.channel, p.product_name, p.product_url,
    p.interest_rate_min, p.interest_rate_max, p.rate_type, p.loan_amount_min,
    p.loan_amount_max, p.tenure_months_max, p.min_monthly_income, p.min_credit_score,
    p.max_credit_score, p.min_age, p.max_age, p.employment_types, p.other_criteria_text,
    p.verification, p.last_seen_at
"""


def get_me(conn: psycopg.Connection, user_id: uuid.UUID) -> dict[str, Any] | None:
    """The borrower's profile, matching state and headline numbers (None = not loaded yet)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT u.user_id, u.name, u.monthly_income, u.credit_score, u.employment_status,
                   u.age, j.job_id, j.source, j.status AS job_status, j.match_status,
                   j.matched_at, s.matches, s.eligible, s.lenders, s.best_rate,
                   s.max_amount
            FROM users u
            LEFT JOIN upload_jobs j ON j.job_id = u.upload_job_id
            CROSS JOIN LATERAL (
                SELECT count(*)::int AS matches,
                       count(*) FILTER (WHERE m.tier = 'eligible')::int AS eligible,
                       count(DISTINCT p.lender_key)::int AS lenders,
                       min(p.interest_rate_min) AS best_rate,
                       max(p.loan_amount_max) AS max_amount
                FROM matches m JOIN loan_products p USING (product_id)
                WHERE m.user_id = u.user_id AND m.status = 'active' AND p.is_active
            ) s
            WHERE u.user_id = %s
            """,
            (user_id,),
        ).fetchone()


def get_matches(conn: psycopg.Connection, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Active matches, best first (eligible, then fit score, then lowest rate)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""
            SELECT m.match_id, m.tier, m.fit_score, m.fit_reasons, m.requirements,
                   m.created_at AS matched_at, {_PRODUCT_COLUMNS}
            FROM matches m JOIN loan_products p USING (product_id)
            WHERE m.user_id = %s AND m.status = 'active' AND p.is_active
            ORDER BY (m.tier = 'eligible') DESC, m.fit_score DESC,
                     p.interest_rate_min NULLS LAST, p.product_name
            """,
            (user_id,),
        ).fetchall()


def get_products(conn: psycopg.Connection, prompt_version: str) -> list[dict[str, Any]]:
    """Every active product with its compiled free-text rules (same join as Stage 1).

    `compiled` is NULL when the conditions were never compiled: the simulator must then
    treat the product as "may qualify", exactly like the SQL does.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""
            SELECT {_PRODUCT_COLUMNS},
                   r.rules AS compiled_rules, r.requirements AS compiled_requirements
            FROM loan_products p
            LEFT JOIN criteria_rules r
                   ON r.prompt_version = %s
                  AND r.criteria_text_hash
                      = encode(sha256(convert_to(p.other_criteria_text, 'UTF8')), 'hex')
            WHERE p.is_active
            ORDER BY p.lender, p.channel, p.product_name
            """,
            (prompt_version,),
        ).fetchall()


def get_preferences(conn: psycopg.Connection, user_id: uuid.UUID) -> dict[str, Any]:
    """Shortlist, top 3, hidden products and the alert toggle (defaults if never saved)."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT shortlist, top3, hidden, alerts, updated_at FROM user_preferences"
            " WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    return row or {"shortlist": [], "top3": [], "hidden": [], "alerts": False, "updated_at": None}


def save_preferences(
    conn: psycopg.Connection, user_id: uuid.UUID, prefs: dict[str, Any]
) -> dict[str, Any]:
    """Upsert the whole preferences row (the client always sends the full state)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            INSERT INTO user_preferences (user_id, shortlist, top3, hidden, alerts)
            VALUES (%(user_id)s, %(shortlist)s, %(top3)s, %(hidden)s, %(alerts)s)
            ON CONFLICT (user_id) DO UPDATE SET
                shortlist = EXCLUDED.shortlist, top3 = EXCLUDED.top3,
                hidden = EXCLUDED.hidden, alerts = EXCLUDED.alerts, updated_at = now()
            RETURNING shortlist, top3, hidden, alerts, updated_at
            """,
            {"user_id": user_id, **prefs},
        ).fetchone()


# ---------------------------------------------------------------- ops view (aggregates only)

OPS_ROWS = 20
ERROR_PREVIEW_CHARS = 160  # enough to recognise a failure, not a stack trace


def ops_runs(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """The latest matching runs: the measured Treasure Hunt funnel, no personal data."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT run_id, mode, status, started_at, finished_at,
                   extract(epoch FROM finished_at - started_at)::numeric(10, 1) AS seconds,
                   users_in, products_in, naive_pairs, pairs_after_sql, classes,
                   class_product_pairs, rule_decided, llm_candidates, llm_cache_hits,
                   llm_calls, llm_input_tokens, llm_output_tokens, llm_cost_usd_est,
                   matches_new, matches_superseded, matches_unchanged, correctness_ok,
                   emails_sent, emails_failed, emails_skipped_demo
            FROM pipeline_runs ORDER BY started_at DESC LIMIT %s
            """,
            (OPS_ROWS,),
        ).fetchall()


def ops_crawl(conn: psycopg.Connection) -> dict[str, Any]:
    """The latest crawl: pages by channel and status, products by channel."""
    with conn.cursor(row_factory=dict_row) as cur:
        latest = cur.execute(
            "SELECT run_id, min(started_at) AS started_at, max(finished_at) AS finished_at"
            " FROM crawl_runs WHERE run_id = (SELECT run_id FROM crawl_runs"
            " ORDER BY started_at DESC LIMIT 1) GROUP BY run_id"
        ).fetchone()
        pages = (
            cur.execute(
                "SELECT channel, status, count(*)::int AS pages,"
                " sum(coalesce(llm_input_tokens, 0) + coalesce(llm_output_tokens, 0))::int"
                " AS llm_tokens"
                " FROM crawl_runs WHERE run_id = %s GROUP BY channel, status"
                " ORDER BY channel, status",
                (latest["run_id"],),
            ).fetchall()
            if latest
            else []
        )
        products = cur.execute(
            "SELECT channel, count(*)::int AS products,"
            " count(*) FILTER (WHERE verification = 'ok')::int AS verified,"
            " count(DISTINCT lender_key)::int AS lenders"
            " FROM loan_products WHERE is_active GROUP BY channel ORDER BY channel"
        ).fetchall()
    return {"latest_run": latest, "pages": pages, "products": products}


def ops_errors(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Recent workflow failures recorded by Workflow E, with a short message preview."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT id, workflow, node, left(message, %s) AS message, created_at"
            " FROM workflow_errors ORDER BY id DESC LIMIT %s",
            (ERROR_PREVIEW_CHARS, OPS_ROWS),
        ).fetchall()
