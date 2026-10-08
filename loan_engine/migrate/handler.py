"""Migrate Lambda: brings the private RDS database to the current schema.

Invoked by hand (`serverless invoke -f migrate`), never by an event. Every step is
idempotent, so running it twice is safe:

1. Apply each numbered `sql/NNN_*.sql` file once, in order, each in its own
   transaction, recorded in `schema_migrations`.
2. Create or refresh the login roles with passwords from Secrets Manager.
3. Re-apply `sql/R__grants.sql` (repeatable, least privilege).
4. Create the `n8n` database owned by `n8n_meta` (n8n's own storage).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from loan_engine.common.db import connect
from loan_engine.common.secrets import fetch_db_credentials

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# /var/task/sql in Lambda; <repo>/sql locally. This file is loan_engine/migrate/handler.py.
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
APP_DB = "app"
N8N_DB = "n8n"
GRANTS_FILE = "R__grants.sql"
_NUMBERED = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True, slots=True)
class RoleSpec:
    """A login role and the env var holding its Secrets Manager ARN."""

    name: str
    secret_env: str


ROLES: tuple[RoleSpec, ...] = (
    RoleSpec("app_ingest", "APP_INGEST_SECRET_ARN"),
    RoleSpec("n8n_workflows", "N8N_WORKFLOWS_SECRET_ARN"),
    RoleSpec("n8n_meta", "N8N_META_SECRET_ARN"),
)


# ---------------------------------------------------------------------------
# Pure logic (unit-tested)
# ---------------------------------------------------------------------------


def numbered_migrations(filenames: list[str]) -> list[str]:
    """Return the numbered migration files sorted by version, ignoring everything else.

    Raises:
        ValueError: if two files share a version number (e.g. 002_a.sql + 002_b.sql),
            which would make the apply order ambiguous.
    """
    by_version: dict[str, str] = {}
    for name in filenames:
        match = _NUMBERED.match(name)
        if not match:
            continue
        version = match.group(1)
        if version in by_version:
            raise ValueError(
                f"duplicate migration version {version}: {by_version[version]}, {name}"
            )
        by_version[version] = name
    return [by_version[v] for v in sorted(by_version)]


def pending_migrations(available: list[str], applied: set[str]) -> list[str]:
    """Numbered migrations not yet recorded in schema_migrations, in apply order."""
    return [name for name in numbered_migrations(available) if name not in applied]


# ---------------------------------------------------------------------------
# Database steps (I/O)
# ---------------------------------------------------------------------------


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply pending numbered migrations; each file + its bookkeeping row is atomic."""
    with conn.transaction():
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   filename   text PRIMARY KEY,
                   applied_at timestamptz NOT NULL DEFAULT now())"""
        )
    applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}
    todo = pending_migrations(sorted(p.name for p in SQL_DIR.glob("*.sql")), applied)
    for name in todo:
        with conn.transaction():
            # A whole file in one execute(): psycopg allows multiple statements when no
            # parameters are passed. The files are our own, shipped inside the package.
            conn.execute((SQL_DIR / name).read_text())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (name,))
        logger.info("applied migration %s", name)
    return todo


def ensure_role(conn: psycopg.Connection, role: str, password: str) -> None:
    """Create the login role if missing, and always (re)set its password from the secret."""
    with conn.transaction():
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
        # The password is sent as a literal over TLS. It never appears in logs or files.
        conn.execute(
            sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )


def apply_grants(conn: psycopg.Connection) -> None:
    """Re-apply the repeatable least-privilege grants."""
    with conn.transaction():
        conn.execute((SQL_DIR / GRANTS_FILE).read_text())


def ensure_n8n_database(autocommit_conn: psycopg.Connection, master_user: str) -> bool:
    """Create the `n8n` database owned by n8n_meta. Returns True if it was created.

    CREATE DATABASE cannot run inside a transaction, hence the autocommit connection.
    On PG 16 the RDS master needs membership in n8n_meta before it may assign
    ownership to it, so we grant that first (the master holds ADMIN on roles it created).
    """
    autocommit_conn.execute(sql.SQL("GRANT n8n_meta TO {}").format(sql.Identifier(master_user)))
    exists = autocommit_conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (N8N_DB,)
    ).fetchone()
    if not exists:
        autocommit_conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER n8n_meta").format(sql.Identifier(N8N_DB))
        )
    # n8n_meta may only reach its own database.
    autocommit_conn.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(N8N_DB))
    )
    return not exists


def summarize(conn: psycopg.Connection) -> dict[str, Any]:
    """Collect evidence for the invoke response: tables, roles, migrations."""
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
    ]
    roles = [
        r[0]
        for r in conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
            ([r.name for r in ROLES],),
        )
    ]
    migrations = [
        r[0] for r in conn.execute("SELECT filename FROM schema_migrations ORDER BY filename")
    ]
    return {"tables": tables, "roles": roles, "migrations": migrations}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Run all migration steps and return a summary as evidence."""
    host = os.environ["DB_HOST"]
    master = fetch_db_credentials(os.environ["MASTER_SECRET_ARN"])

    # autocommit=True + explicit conn.transaction() blocks: each block is a real
    # BEGIN/COMMIT. Without autocommit, the first SELECT would open an implicit
    # transaction and every later block would silently become a mere savepoint.
    with connect(host, APP_DB, master, autocommit=True, application_name="migrate") as conn:
        applied_now = apply_migrations(conn)
        for role in ROLES:
            creds = fetch_db_credentials(os.environ[role.secret_env])
            ensure_role(conn, role.name, creds.password)
        apply_grants(conn)
        summary = summarize(conn)

    with connect(host, "postgres", master, autocommit=True, application_name="migrate") as conn:
        n8n_db_created = ensure_n8n_database(conn, master.username)

    result = {"applied_now": applied_now, "n8n_db_created": n8n_db_created, **summary}
    logger.info("migrate finished: %s", result)
    return result
