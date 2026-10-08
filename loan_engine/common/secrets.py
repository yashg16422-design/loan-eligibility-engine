"""Read database credentials from AWS Secrets Manager.

Lambdas reach Secrets Manager through the VPC interface endpoint (no internet).
Nothing secret is ever passed in environment variables, only the secret ARN.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache

import boto3


@dataclass(frozen=True, slots=True)
class DbCredentials:
    """A Postgres username/password pair. `repr` hides the password from logs."""

    username: str
    password: str

    def __repr__(self) -> str:
        return f"DbCredentials(username={self.username!r}, password='***')"


def parse_db_secret(secret_string: str) -> DbCredentials:
    """Parse the JSON stored by RDS or by our generated secrets.

    Both formats carry at least {"username": ..., "password": ...}.

    Raises:
        ValueError: if either key is missing or empty.
    """
    data = json.loads(secret_string)
    username, password = data.get("username"), data.get("password")
    if not username or not password:
        raise ValueError("secret must contain non-empty 'username' and 'password'")
    return DbCredentials(username=username, password=password)


def fetch_db_credentials(secret_arn: str) -> DbCredentials:
    """Fetch credentials fresh on every call.

    Used for the RDS-managed master secret, which RDS rotates every 7 days:
    caching it could leave a warm Lambda holding a stale password.
    """
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    return parse_db_secret(response["SecretString"])


@cache
def cached_db_credentials(secret_arn: str) -> DbCredentials:
    """Fetch once per Lambda container (cold start) and reuse.

    Safe for the app-role secrets: they have no automatic rotation (PLAN.md §7).
    """
    return fetch_db_credentials(secret_arn)
