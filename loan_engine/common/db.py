"""Postgres connection helper shared by all Lambdas."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import psycopg

from loan_engine.common.secrets import DbCredentials

# Three tries of 8 s: a matching run writing hundreds of thousands of rows can make RDS slow to
# accept a new connection (seen live). 3 x 8 s + pauses stays inside the api's 28 s budget.
CONNECT_ATTEMPTS = 3
CONNECT_TIMEOUT_S = 8
RETRY_PAUSE_SECONDS = 0.5
# Amazon's RDS CA bundle for ap-southeast-2 (https://truststore.pki.rds.amazonaws.com), shipped
# inside the package so verification needs no network call.
RDS_CA_BUNDLE = Path(__file__).with_name("certs") / "rds-ap-southeast-2-bundle.pem"


def tls_options(env: Mapping[str, str]) -> dict[str, Any]:
    """libpq TLS settings from the environment.

    DB_SSLMODE=verify-full (the deployed Lambdas): encrypted AND the server certificate must be
    signed by the RDS CA and match the hostname. Unset = `require` (encrypted, not verified),
    which local tests and CI use with their self-signed Postgres. Rollback = set it to require.
    """
    mode = env.get("DB_SSLMODE", "require")
    if mode in ("verify-ca", "verify-full"):
        return {"sslmode": mode, "sslrootcert": env.get("DB_SSLROOTCERT", str(RDS_CA_BUNDLE))}
    return {"sslmode": mode}


def connect(
    host: str,
    dbname: str,
    creds: DbCredentials,
    *,
    port: int = 5432,
    autocommit: bool = False,
    application_name: str = "loan-engine",
    attempts: int = CONNECT_ATTEMPTS,
) -> psycopg.Connection:
    """Open a TLS connection to RDS (see tls_options: verify-full in the deployed Lambdas).

    A failed connect is retried (a transient network blip must not fail a request). Callers
    with time to spare (ingest) pass more `attempts` to outlast a busy database.
    """
    for attempt in range(1, attempts + 1):
        try:
            return psycopg.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=creds.username,
                password=creds.password,
                **tls_options(os.environ),
                connect_timeout=CONNECT_TIMEOUT_S,  # bounded: a hang must not burn the budget
                autocommit=autocommit,
                application_name=application_name,
            )
        except psycopg.OperationalError:
            # Safe to retry: nothing has been sent yet. A wrong password fails twice, fast.
            if attempt == attempts:
                raise
            time.sleep(RETRY_PAUSE_SECONDS * attempt)
    raise AssertionError("unreachable")
