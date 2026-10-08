"""Postgres connection helper shared by all Lambdas."""

from __future__ import annotations

import psycopg

from loan_engine.common.secrets import DbCredentials


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
    """
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
