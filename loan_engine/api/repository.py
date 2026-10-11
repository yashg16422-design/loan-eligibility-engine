"""All SQL used by the api Lambda (runs as the least-privilege `app_ingest` role)."""

from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

REJECTS_SHOWN = 20


def _one(row: dict[str, Any] | None) -> dict[str, Any]:
    """The single row of an INSERT ... RETURNING or an aggregate query (always exactly one)."""
    if row is None:
        raise RuntimeError("expected one row, got none")
    return row


def create_job(
    conn: psycopg.Connection,
    job_id: uuid.UUID,
    s3_key: str,
    filename: str | None,
    source: str = "csv",
    account_id: str | None = None,
    requester_hash: str | None = None,
) -> None:
    """Register the upload ticket before any file can reach S3 for it (owned by an account)."""
    conn.execute(
        "INSERT INTO upload_jobs (job_id, s3_key, original_filename, source, account_id,"
        " requester_hash) VALUES (%s, %s, %s, %s, %s, %s)",
        (job_id, s3_key, filename, source, account_id, requester_hash),
    )


def upload_owner(conn: psycopg.Connection, job_id: uuid.UUID) -> tuple[bool, str | None]:
    """(exists, owning account) for a bulk upload."""
    row = conn.execute(
        "SELECT account_id FROM upload_jobs WHERE job_id = %s AND source = 'csv'", (job_id,)
    ).fetchone()
    return (row is not None, row[0] if row else None)


def csv_uploads_last_24h(conn: psycopg.Connection, account_id: str | None = None) -> int:
    """Upload tickets issued in the last 24 h (each can trigger emails: the SES-quota guard),
    for every account, or for one account when `account_id` is given."""
    row = conn.execute(
        "SELECT count(*) FROM upload_jobs"
        " WHERE source = 'csv' AND created_at > now() - interval '24 hours'"
        " AND (%(account)s::text IS NULL OR account_id = %(account)s::text)",
        {"account": account_id},
    ).fetchone()
    return int(row[0]) if row else 0


def awaiting_notification(conn: psycopg.Connection, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """The subset of users Workflow C is about to email: an active, not-yet-notified match."""
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM matches"
        " WHERE user_id = ANY(%s) AND status = 'active' AND notified_at IS NULL",
        (user_ids,),
    ).fetchall()
    return {r[0] for r in rows}


def instant_checks_last_24h(conn: psycopg.Connection, requester: str | None = None) -> int:
    """How many instant checks ran in the last 24 h (the SES-quota guard), in total or from one
    requester (a salted hash of the source IP; the raw IP is never stored)."""
    row = conn.execute(
        "SELECT count(*) FROM upload_jobs"
        " WHERE source = 'instant_check' AND created_at > now() - interval '24 hours'"
        " AND (%(requester)s::text IS NULL OR requester_hash = %(requester)s::text)",
        {"requester": requester},
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
        return _one(
            cur.execute(
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
        )


# ---------------------------------------------------------------- ops view (aggregates only)

OPS_ROWS = 20
ERROR_PREVIEW_CHARS = 160  # enough to recognise a failure, not a stack trace


_RUN_COLUMNS = """
    run_id, mode, job_id, status, started_at, finished_at,
    extract(epoch FROM finished_at - started_at)::numeric(10, 1) AS seconds,
    users_in, products_in, naive_pairs, pairs_after_sql, classes,
    class_product_pairs, rule_decided, llm_candidates, llm_cache_hits,
    llm_calls, llm_input_tokens, llm_output_tokens, llm_cost_usd_est,
    matches_new, matches_superseded, matches_unchanged, correctness_ok,
    emails_sent, emails_failed, emails_skipped_demo,
    (SELECT j.purged_at IS NOT NULL FROM upload_jobs j
       WHERE j.job_id = pipeline_runs.job_id) AS purged,
    (SELECT j.account_id IS NOT NULL FROM upload_jobs j
       WHERE j.job_id = pipeline_runs.job_id) AS owned
"""

# The public showcase dataset: the largest completed upload that belongs to no one or to an
# admin (the operator), and whose customers are still stored. Another merchant's upload can
# never become public this way, however large it is.
_REFERENCE_RUN = f"""
    SELECT {_RUN_COLUMNS} FROM pipeline_runs
    WHERE mode = 'upload' AND status = 'done'
      AND EXISTS (SELECT 1 FROM upload_jobs ref
                  WHERE ref.job_id = pipeline_runs.job_id AND ref.source = 'csv'
                    AND ref.purged_at IS NULL
                    AND (ref.account_id IS NULL
                         OR ref.account_id IN (SELECT account_id FROM accounts WHERE is_admin)))
    ORDER BY users_in DESC NULLS LAST, started_at DESC LIMIT 1
"""


def reference_job(conn: psycopg.Connection) -> uuid.UUID | None:
    """The job behind the public reference dataset (see _REFERENCE_RUN), if there is one."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(_REFERENCE_RUN).fetchone()
    return row["job_id"] if row else None


def ops_runs(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """The latest matching runs: the measured Treasure Hunt funnel, no personal data.

    The reference run (_REFERENCE_RUN: the operator's full-file upload) is always included and
    flagged `reference`, so newer small runs never push it out of view. This list is public:
    a run whose upload belongs to a merchant keeps its counters but not its job_id, so nobody
    can address another account's upload from here.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        runs = cur.execute(
            f"SELECT {_RUN_COLUMNS} FROM pipeline_runs ORDER BY started_at DESC LIMIT %s",
            (OPS_ROWS,),
        ).fetchall()
        reference = cur.execute(_REFERENCE_RUN).fetchone()
    for run in runs:
        run["reference"] = reference is not None and run["run_id"] == reference["run_id"]
    if reference is not None and not any(r["reference"] for r in runs):
        runs.append({**reference, "reference": True})
    for run in runs:
        if run.pop("owned", False) and not run["reference"]:
            run["job_id"] = None
    return runs


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


# ---------------------------------------------------------------- accounts (Cognito)


def upsert_account(
    conn: psycopg.Connection, account_id: str, email: str, admin: bool = False
) -> dict[str, Any]:
    """The account row for a signed-in person: ONE per verified email.

    Cognito gives each sign-in method its own user (`sub`): a password account and a Google
    sign-in with the same address are two users. Both emails are verified (by code, or by
    Google), so the address is the person: an existing row with that email is reused, and its
    account_id is returned for ownership. A new email creates a row keyed by this sub.
    `admin` (a Cognito admin group member) is recorded on the row and never cleared here.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        return _one(
            cur.execute(
                """
            WITH found AS (
                UPDATE accounts SET last_seen_at = now(), is_admin = is_admin OR %(admin)s
                WHERE lower(email) = lower(%(email)s)
                RETURNING account_id, email, daily_picks, created_at, is_admin
            ), created AS (
                INSERT INTO accounts (account_id, email, is_admin)
                SELECT %(sub)s, %(email)s, %(admin)s WHERE NOT EXISTS (SELECT 1 FROM found)
                ON CONFLICT (account_id) DO UPDATE SET email = EXCLUDED.email, last_seen_at = now(),
                    is_admin = accounts.is_admin OR EXCLUDED.is_admin
                RETURNING account_id, email, daily_picks, created_at, is_admin
            )
            SELECT * FROM found UNION ALL SELECT * FROM created
            """,
                {"sub": account_id, "email": email, "admin": admin},
            ).fetchone()
        )


def account_profiles(conn: psycopg.Connection, account_id: str) -> list[dict[str, Any]]:
    """The checks this account saved, newest first, with their headline numbers."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT u.user_id, u.name, u.monthly_income, u.credit_score, u.employment_status,
                   u.age, ap.saved_at, coalesce(j.source, 'csv') AS source,
                   count(m.*) FILTER (WHERE m.status = 'active')::int AS matches,
                   count(m.*) FILTER (WHERE m.status = 'active' AND m.tier = 'eligible')::int
                       AS eligible
            FROM account_profiles ap
            JOIN users u USING (user_id)
            LEFT JOIN upload_jobs j ON j.job_id = u.upload_job_id
            LEFT JOIN matches m ON m.user_id = u.user_id
            WHERE ap.account_id = %s
            GROUP BY u.user_id, ap.saved_at, j.source
            ORDER BY ap.saved_at DESC
            """,
            (account_id,),
        ).fetchall()


def set_daily_picks(conn: psycopg.Connection, account_id: str, on: bool) -> None:
    conn.execute("UPDATE accounts SET daily_picks = %s WHERE account_id = %s", (on, account_id))


def claim_profile(conn: psycopg.Connection, account_id: str, user_id: uuid.UUID) -> str:
    """Link a checked profile to an account.

    Returns "saved", "already_saved" (this account), "taken" (another account owns it) or
    "not_found" (the check has not been loaded yet). The UNIQUE(user_id) constraint makes
    "first saver owns it" hold even under a race.
    """
    if conn.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,)).fetchone() is None:
        return "not_found"
    row = conn.execute(
        """
        INSERT INTO account_profiles (account_id, user_id) VALUES (%s, %s)
        ON CONFLICT (user_id) DO NOTHING
        RETURNING 1
        """,
        (account_id, user_id),
    ).fetchone()
    if row:
        return "saved"
    owner = conn.execute(
        "SELECT account_id FROM account_profiles WHERE user_id = %s", (user_id,)
    ).fetchone()
    return "already_saved" if owner and owner[0] == account_id else "taken"


def owns_profile(conn: psycopg.Connection, account_id: str, user_id: uuid.UUID) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM account_profiles WHERE account_id = %s AND user_id = %s",
            (account_id, user_id),
        ).fetchone()
        is not None
    )


# ---------------------------------------------------------------- data reset

# Child rows (matches, notifications, preferences, account links) go with each user by
# ON DELETE CASCADE. Lender products, pipeline_runs (the Treasure Hunt evidence) and the
# upload_jobs rows always stay; a cleared upload is stamped purged_at.


class JobBusyError(Exception):
    """The upload is loading, matching or being emailed; deleting now would cut a run in half."""


# Workflow C emails right after Stage 3 stamps matched_at; a user deleted under it would make
# its notification insert fail. Two minutes covers a C run with room to spare.
_BUSY = (
    "status = 'PROCESSING' OR match_status = 'RUNNING' OR matched_at > now() - interval '2 minutes'"
)


EMAIL_PREVIEWS = 3


def email_previews(conn: psycopg.Connection, job_id: uuid.UUID) -> list[dict[str, Any]]:
    """Up to 3 of an upload's customers as Workflow C emails them: the customers who were sent
    an email first (with the test inbox it went to), each with the same top picks C chose
    (best offer per lender, ranked by tier, fit score, then rate)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            WITH who AS (
                SELECT u.user_id, u.name, n.alias_email, n.created_at AS sent_at
                FROM users u
                LEFT JOIN LATERAL (
                    SELECT alias_email, created_at FROM notifications
                    WHERE user_id = u.user_id AND status = 'sent'
                    ORDER BY created_at DESC LIMIT 1
                ) n ON true
                WHERE u.upload_job_id = %(job)s
                  AND EXISTS (SELECT 1 FROM matches m
                              WHERE m.user_id = u.user_id AND m.status = 'active')
                ORDER BY n.created_at IS NULL, u.user_id
                LIMIT %(n)s
            ), active AS (
                SELECT m.user_id, m.tier, m.requirements, m.fit_score, p.lender, p.lender_key,
                       p.channel, p.product_name, p.interest_rate_min, p.interest_rate_max
                FROM matches m JOIN loan_products p USING (product_id) JOIN who USING (user_id)
                WHERE m.status = 'active' AND p.is_active
            ), best AS (
                SELECT DISTINCT ON (user_id, lender_key) * FROM active
                ORDER BY user_id, lender_key, (tier = 'eligible') DESC, fit_score DESC,
                         interest_rate_min NULLS LAST, product_name
            ), ranked AS (
                SELECT *, row_number() OVER (PARTITION BY user_id ORDER BY (tier = 'eligible') DESC,
                       fit_score DESC, interest_rate_min NULLS LAST, product_name) AS rnk
                FROM best
            )
            SELECT w.user_id, w.name, w.alias_email, w.sent_at,
                   (SELECT count(*) FROM active a
                     WHERE a.user_id = w.user_id)::int AS matches_total,
                   (SELECT count(DISTINCT lender_key) FROM active a
                     WHERE a.user_id = w.user_id)::int AS lenders_total,
                   coalesce((SELECT json_agg(json_build_object(
                        'lender', r.lender, 'channel', r.channel, 'tier', r.tier,
                        'requirements', r.requirements, 'interest_rate_min', r.interest_rate_min,
                        'interest_rate_max', r.interest_rate_max) ORDER BY r.rnk)
                     FROM ranked r WHERE r.user_id = w.user_id AND r.rnk <= 5), '[]') AS picks
            FROM who w
            ORDER BY w.sent_at IS NULL, w.user_id
            """,
            {"job": job_id, "n": EMAIL_PREVIEWS},
        ).fetchall()


UPLOADS_SHOWN = 20


def list_uploads(conn: psycopg.Connection, account_id: str | None) -> list[dict[str, Any]]:
    """Recent bulk uploads of one account (None = every account, for admins), one record each:
    counts only, no personal data.

    `users_now` is how many of the users this file added or changed are still in the database
    (0 after a delete); tickets whose file never arrived are left out after 15 minutes.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            WITH j AS (
                SELECT job_id, original_filename, status, created_at, completed_at, total_rows,
                       inserted, updated, unchanged, rejected, match_status, matched_at, purged_at
                FROM upload_jobs
                WHERE source = 'csv'
                  AND (%s::text IS NULL OR account_id = %s::text)
                  AND (status <> 'AWAITING_UPLOAD' OR created_at > now() - interval '15 minutes')
                ORDER BY created_at DESC LIMIT %s
            )
            SELECT j.*,
                   (SELECT count(*) FROM users u WHERE u.upload_job_id = j.job_id)::int
                       AS users_now,
                   -- Matches found for the file, from its runs' own counter: counting the
                   -- active matches live read ~260k rows per 10k upload on every page load
                   -- (17 s while a run kept RDS busy). A cleared upload has none left.
                   (CASE WHEN j.purged_at IS NOT NULL THEN 0
                         ELSE (SELECT coalesce(sum(r.matches_new), 0) FROM pipeline_runs r
                               WHERE r.job_id = j.job_id AND r.status = 'done') END)::int
                       AS matches,
                   (SELECT count(*) FROM notifications n
                     WHERE n.job_id = j.job_id AND n.status = 'sent')::int AS emails_sent
            FROM j ORDER BY j.created_at DESC
            """,
            (account_id, account_id, UPLOADS_SHOWN),
        ).fetchall()


# Deletes run in chunks: one 10,000-customer upload cascades to ~260,000 matches, which took
# longer than the API timeout in one transaction (found live). Each chunk is its own short
# transaction, and a call stops after a time budget and reports what is left; the client calls
# again until nothing is. A half-deleted upload is simply resumed by the next call.
PURGE_CHUNK = 2000
PURGE_BUDGET_S = 15.0


def users_left(conn: psycopg.Connection, job_id: uuid.UUID) -> int:
    row = conn.execute("SELECT count(*) FROM users WHERE upload_job_id = %s", (job_id,)).fetchone()
    return int(row[0]) if row else 0


def purge_upload(
    conn: psycopg.Connection,
    job_id: uuid.UUID,
    chunk: int = PURGE_CHUNK,
    budget_s: float = PURGE_BUDGET_S,
) -> int | None:
    """Delete (part of) the users one upload added or changed, so the same file can be uploaded
    as new. Returns how many were deleted by this call (users_left tells what remains), or None
    if the job does not exist. The job row is locked in every chunk, so ingest or Workflow B
    cannot claim it halfway; it is stamped purged_at once no user is left.
    """
    started, deleted = time.monotonic(), 0
    while True:
        with conn.transaction():
            row = conn.execute(
                f"SELECT {_BUSY} FROM upload_jobs WHERE job_id = %s FOR UPDATE", (job_id,)
            ).fetchone()
            if row is None:
                return None
            if row[0]:
                raise JobBusyError
            n = conn.execute(
                "DELETE FROM users WHERE user_id IN"
                " (SELECT user_id FROM users WHERE upload_job_id = %s LIMIT %s)",
                (job_id, chunk),
            ).rowcount
            deleted += n
            if n < chunk:
                conn.execute(
                    "UPDATE upload_jobs SET purged_at = now() WHERE job_id = %s", (job_id,)
                )
                return deleted
        if time.monotonic() - started > budget_s:
            return deleted


def purge_csv_uploads(
    conn: psycopg.Connection,
    account_id: str | None = None,
    chunk: int = PURGE_CHUNK,
    budget_s: float = PURGE_BUDGET_S,
) -> dict[str, int]:
    """Delete the customers of one account's uploads ("reset my workspace"), or of every
    bulk upload when account_id is None (admins), in chunks (see PURGE_CHUNK).

    Returns what this call deleted, how many uploads are now fully cleared, and how many
    customers are still left for the next call. Instant checks stay: they belong to the people
    who ran them, who can delete their own.
    """
    mine = "(%(a)s::text IS NULL OR account_id = %(a)s::text)"
    started, deleted, uploads = time.monotonic(), 0, 0
    while True:
        with conn.transaction():
            busy = conn.execute(
                f"SELECT bool_or({_BUSY}) FROM"
                " (SELECT status, match_status, matched_at FROM upload_jobs"
                f" WHERE source = 'csv' AND {mine} FOR UPDATE) j",
                {"a": account_id},
            ).fetchone()
            if busy and busy[0]:
                raise JobBusyError
            n = conn.execute(
                "DELETE FROM users WHERE user_id IN (SELECT u.user_id FROM users u"
                " JOIN upload_jobs j ON j.job_id = u.upload_job_id WHERE j.source = 'csv'"
                " AND (%(a)s::text IS NULL OR j.account_id = %(a)s::text) LIMIT %(n)s)",
                {"a": account_id, "n": chunk},
            ).rowcount
            deleted += n
            uploads += conn.execute(
                "UPDATE upload_jobs j SET purged_at = now()"
                f" WHERE source = 'csv' AND purged_at IS NULL AND {mine}"
                " AND NOT EXISTS (SELECT 1 FROM users u WHERE u.upload_job_id = j.job_id)",
                {"a": account_id},
            ).rowcount
            if n < chunk:
                return {"deleted_users": deleted, "uploads": uploads, "remaining": 0}
        if time.monotonic() - started > budget_s:
            row = conn.execute(
                "SELECT count(*) FROM users u JOIN upload_jobs j ON j.job_id = u.upload_job_id"
                " WHERE j.source = 'csv' AND (%(a)s::text IS NULL OR j.account_id = %(a)s::text)",
                {"a": account_id},
            ).fetchone()
            left = int(row[0]) if row else 0
            return {"deleted_users": deleted, "uploads": uploads, "remaining": left}


def cancel_upload(conn: psycopg.Connection, job_id: uuid.UUID) -> str | None:
    """Stop an upload. Before its file is loaded it is cancelled for real ("cancelled": the job
    is FAILED, so a later SQS delivery of the file is ignored by ingest's claim). Once loaded,
    matching runs in n8n and cannot be stopped halfway ("running"), or it is already over
    ("finished"). None if the job does not exist.
    """
    with conn.transaction():
        row = conn.execute(
            "SELECT status, match_status FROM upload_jobs WHERE job_id = %s FOR UPDATE", (job_id,)
        ).fetchone()
        if row is None:
            return None
        status, match_status = row
        if status in ("AWAITING_UPLOAD", "PROCESSING"):
            conn.execute(
                "UPDATE upload_jobs SET status = 'FAILED', completed_at = now(),"
                " error = 'Cancelled by you before the file was loaded.' WHERE job_id = %s",
                (job_id,),
            )
            return "cancelled"
        if status == "COMPLETED" and match_status in (None, "RUNNING"):
            return "running"
        return "finished"


def delete_check(conn: psycopg.Connection, user_id: uuid.UUID) -> str:
    """A person deletes their own instant check: "deleted", "not_found", "csv_user" or "busy".

    Users from a bulk upload are the operator's data, so a dashboard link cannot delete them.
    """
    row = conn.execute(
        f"SELECT j.source, coalesce({_BUSY}, false) FROM users u"
        " LEFT JOIN upload_jobs j ON j.job_id = u.upload_job_id WHERE u.user_id = %s",
        (user_id,),
    ).fetchone()
    if row is None:
        return "not_found"
    if row[0] != "instant_check":
        return "csv_user"
    if row[1]:
        return "busy"
    conn.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
    return "deleted"


def clear_account_profiles(
    conn: psycopg.Connection, account_id: str, user_id: uuid.UUID | None = None
) -> dict[str, int]:
    """Start fresh: remove this account's saved checks (one, or all). The account stays.

    The account's own instant checks are deleted outright; a bulk-upload profile it saved is
    only unlinked, because that row is the operator's data.
    """
    scope = "ap.account_id = %(a)s AND (%(u)s::uuid IS NULL OR ap.user_id = %(u)s::uuid)"
    with conn.transaction():
        deleted = conn.execute(
            "DELETE FROM users u USING account_profiles ap, upload_jobs j"
            " WHERE ap.user_id = u.user_id AND j.job_id = u.upload_job_id"
            f" AND j.source = 'instant_check' AND NOT ({_BUSY}) AND {scope}",
            {"a": account_id, "u": user_id},
        ).rowcount
        unlinked = conn.execute(
            f"DELETE FROM account_profiles ap WHERE {scope}", {"a": account_id, "u": user_id}
        ).rowcount
    return {"deleted_checks": deleted, "unlinked": unlinked}


# ---------------------------------------------------------------- CSV analytics (aggregates)

# Band edges match the measured profile of the sample file (PLAN.md §9): income 25k-150k,
# scores 650-800, ages 22-50, with room either side for other files.
_ANALYTICS_SQL = """
WITH u AS (
    SELECT * FROM users WHERE %(job)s::uuid IS NULL OR upload_job_id = %(job)s::uuid
), m AS (
    SELECT m.user_id, m.tier, p.lender, p.lender_key, p.channel
    FROM matches m JOIN loan_products p USING (product_id) JOIN u USING (user_id)
    WHERE m.status = 'active'
), per_user AS (
    SELECT u.user_id, count(m.user_id) AS n,
           count(m.user_id) FILTER (WHERE m.tier = 'eligible') AS eligible
    FROM u LEFT JOIN m USING (user_id) GROUP BY u.user_id
)
SELECT
  (SELECT count(*) FROM u)::int AS users,
  (SELECT count(*) FROM m)::int AS matches,
  (SELECT count(*) FROM per_user WHERE eligible > 0)::int AS users_with_eligible,
  (SELECT count(*) FROM per_user WHERE n = 0)::int AS users_without_matches,
  (SELECT coalesce(json_agg(x ORDER BY x.ord), '[]') FROM (
      SELECT CASE WHEN monthly_income < 25000 THEN 0 WHEN monthly_income < 50000 THEN 1
                  WHEN monthly_income < 75000 THEN 2 WHEN monthly_income < 100000 THEN 3
                  WHEN monthly_income < 125000 THEN 4 ELSE 5 END AS ord, count(*)::int AS n
      FROM u GROUP BY 1) x) AS income_bands,
  (SELECT coalesce(json_agg(x ORDER BY x.ord), '[]') FROM (
      SELECT CASE WHEN credit_score < 650 THEN 0 WHEN credit_score < 700 THEN 1
                  WHEN credit_score < 750 THEN 2 WHEN credit_score < 800 THEN 3 ELSE 4 END AS ord,
             count(*)::int AS n
      FROM u GROUP BY 1) x) AS score_bands,
  (SELECT coalesce(json_agg(x ORDER BY x.ord), '[]') FROM (
      SELECT CASE WHEN age < 25 THEN 0 WHEN age < 30 THEN 1 WHEN age < 35 THEN 2
                  WHEN age < 40 THEN 3 WHEN age < 45 THEN 4 ELSE 5 END AS ord, count(*)::int AS n
      FROM u GROUP BY 1) x) AS age_bands,
  (SELECT coalesce(json_agg(x ORDER BY x.n DESC), '[]') FROM (
      SELECT employment_status AS key, count(*)::int AS n FROM u GROUP BY 1) x) AS employment,
  (SELECT coalesce(json_agg(x ORDER BY x.ord), '[]') FROM (
      SELECT CASE WHEN n = 0 THEN 0 WHEN n <= 10 THEN 1 WHEN n <= 20 THEN 2 WHEN n <= 30 THEN 3
                  WHEN n <= 40 THEN 4 ELSE 5 END AS ord, count(*)::int AS n
      FROM per_user GROUP BY 1) x) AS matches_per_user,
  (SELECT coalesce(json_agg(x ORDER BY x.n DESC), '[]') FROM (
      SELECT tier AS key, count(*)::int AS n FROM m GROUP BY 1) x) AS tiers,
  (SELECT coalesce(json_agg(x ORDER BY x.n DESC), '[]') FROM (
      SELECT channel AS key, count(*)::int AS n FROM m GROUP BY 1) x) AS channels,
  (SELECT coalesce(json_agg(x ORDER BY x.users DESC, x.lender), '[]') FROM (
      SELECT lender, count(DISTINCT user_id)::int AS users,
             count(DISTINCT user_id) FILTER (WHERE tier = 'eligible')::int AS eligible_users
      FROM m GROUP BY lender ORDER BY 3 DESC, 2 DESC, 1 LIMIT 10) x) AS top_lenders
"""


def analytics_version(conn: psycopg.Connection, job_id: uuid.UUID) -> tuple[Any, ...] | None:
    """What an upload's analytics depend on: when it was last matched and whether its customers
    were deleted. Unchanged version = unchanged charts (the api caches on it)."""
    row = conn.execute(
        "SELECT matched_at, purged_at FROM upload_jobs WHERE job_id = %s", (job_id,)
    ).fetchone()
    return tuple(row) if row else None


def stored_analytics(conn: psycopg.Connection, job_id: uuid.UUID, version: str) -> Any:  # noqa: ANN401 - JSON
    """The analytics computed earlier for this exact version of the upload, or None."""
    row = conn.execute(
        "SELECT payload FROM analytics_cache WHERE job_id = %s AND version = %s", (job_id, version)
    ).fetchone()
    return row[0] if row else None


def analytics_snapshot(conn: psycopg.Connection, job_id: uuid.UUID) -> Any:  # noqa: ANN401 - JSON
    """The last analytics stored for an upload, whatever its version: what the charts showed
    before its customer records were deleted."""
    row = conn.execute(
        "SELECT payload FROM analytics_cache WHERE job_id = %s", (job_id,)
    ).fetchone()
    return row[0] if row else None


def store_analytics(
    conn: psycopg.Connection, job_id: uuid.UUID, version: str, payload: dict[str, Any]
) -> None:
    """Keep the analytics for this version (shared by every api container)."""
    conn.execute(
        "INSERT INTO analytics_cache (job_id, version, payload) VALUES (%s, %s, %s)"
        " ON CONFLICT (job_id) DO UPDATE SET version = EXCLUDED.version,"
        " payload = EXCLUDED.payload, computed_at = now()",
        (job_id, version, Jsonb(payload, dumps=_json_dumps)),
    )


def _json_dumps(value: object) -> str:
    """JSON for stored payloads: database decimals become numbers, dates ISO strings."""

    def default(o: object) -> object:
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        raise TypeError(f"not JSON serializable: {type(o).__name__}")

    return json.dumps(value, default=default)


def analytics(conn: psycopg.Connection, job_id: uuid.UUID | None) -> dict[str, Any]:
    """Distributions for one upload's users (or every user): profiles, matches, lenders.

    Aggregates only: no names, no emails, no ids leave the database.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        return _one(cur.execute(_ANALYTICS_SQL, {"job": job_id}).fetchone())
