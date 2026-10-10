"""Derived job states and the JSON shape the UI polls (pure functions)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

# A ticket whose file never arrived is reported EXPIRED after this long.
# The presigned POST itself expires after 10 minutes; 15 leaves slack for slow uploads.
EXPIRE_AFTER = timedelta(minutes=15)
# A 10,000-row load takes seconds; a first attempt still "waiting" after this has failed.
FIRST_ATTEMPT_MAX = timedelta(minutes=3)


def derive_status(status: str, attempts: int, created_at: datetime, now: datetime) -> str:
    """Add the two states that are computed, never stored (PLAN.md §5.1).

    - EXPIRED: still waiting, no recorded ingest attempt, and older than 15 minutes: the
      browser never uploaded the file, or ingest crashed before it could record an attempt
      (that message is in the DLQ and the DLQ alarm has fired).
    - PROCESSING: the first ingest attempt is running (its counter is already committed).
    - RETRYING: still waiting after a failed attempt; SQS will redeliver.
    """
    if status != "AWAITING_UPLOAD":
        return status
    # The attempt counter is committed BEFORE the load transaction, so "1 attempt, still
    # waiting" also describes a first attempt that is running right now (seen live on a
    # 10,000-row file). Only a second attempt, or a first one older than any real load, means
    # an attempt failed and SQS is redelivering.
    if attempts > 1 or (attempts == 1 and now - created_at > FIRST_ATTEMPT_MAX):
        return "RETRYING"
    if attempts == 1:
        return "PROCESSING"
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
