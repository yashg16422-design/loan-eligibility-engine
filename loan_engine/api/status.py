"""Derived job states and the JSON shape the UI polls (pure functions)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

# A ticket whose file never arrived is reported EXPIRED after this long.
# The presigned POST itself expires after 10 minutes; 15 leaves slack for slow uploads.
EXPIRE_AFTER = timedelta(minutes=15)


def derive_status(status: str, attempts: int, created_at: datetime, now: datetime) -> str:
    """Add the two states that are computed, never stored (PLAN.md §5.1).

    - EXPIRED: still waiting, no ingest attempt ever, and older than 15 minutes:
      the browser never uploaded the file.
    - RETRYING: still waiting but at least one ingest attempt failed; SQS will redeliver.
    """
    if status != "AWAITING_UPLOAD":
        return status
    if attempts > 0:
        return "RETRYING"
    if now - created_at > EXPIRE_AFTER:
        return "EXPIRED"
    return status


def to_json_safe(value: object) -> object:
    """Make DB values JSON-serializable: datetimes -> ISO, Decimals -> floats, UUIDs -> str."""
    if isinstance(value, uuid.UUID):  # psycopg returns uuid columns as uuid.UUID
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_json_safe(v) for v in value]
    return value
