"""Postgres connection helper shared by all Lambdas."""

from __future__ import annotations

import time

import psycopg

from loan_engine.common.secrets import DbCredentials

CONNECT_ATTEMPTS = 2  # one retry: seen live, a single connect timed out while RDS was idle
RETRY_PAUSE_SECONDS = 0.3


def connect(
    host: str,
    dbname: str,
    creds: DbCredentials,
    *,
    port: int = 5432,
    autocommit: bool = False,
    application_name: str = "loan-engine",
) -> psycopg.Connection:
    """Open a TLS connection to RDS.

    sslmode=require: RDS (PG >= 15) refuses non-TLS connections anyway
    (rds.force_ssl=1). Certificate verification (verify-full + the RDS CA
    bundle) is a listed hardening step; traffic never leaves the private VPC.
    A failed connect is retried once (a transient network blip must not fail a request).
    """
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            return psycopg.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=creds.username,
                password=creds.password,
                sslmode="require",
                connect_timeout=5,  # fail fast: a hanging connect would burn the Lambda timeout
                autocommit=autocommit,
                application_name=application_name,
            )
        except psycopg.OperationalError:
            # Safe to retry: nothing has been sent yet. A wrong password fails twice, fast.
            if attempt == CONNECT_ATTEMPTS:
                raise
            time.sleep(RETRY_PAUSE_SECONDS)
    raise AssertionError("unreachable")
