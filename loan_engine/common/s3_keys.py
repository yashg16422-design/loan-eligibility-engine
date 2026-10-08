"""The S3 key contract between the upload API and the ingest Lambda.

The API pins every presigned POST to exactly `raw/<job_id>.csv`, so the key IS the
claim ticket. The ingest side trusts nothing else: a key that doesn't match the
pattern is never used to touch the database.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import unquote_plus

RAW_PREFIX = "raw/"
_RAW_KEY = re.compile(r"^raw/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.csv$")


def raw_key_for(job_id: uuid.UUID) -> str:
    """The one S3 key a job's upload may use."""
    return f"{RAW_PREFIX}{job_id}.csv"


def job_id_from_event_key(event_key: str) -> uuid.UUID | None:
    """Extract the job id from a key as it appears in an S3 event, or None.

    S3 event keys are URL-encoded with '+' for spaces, hence unquote_plus.
    Only the exact lowercase pattern produced by `raw_key_for` is accepted.
    """
    key = unquote_plus(event_key)
    match = _RAW_KEY.fullmatch(key)
    return uuid.UUID(match.group(1)) if match else None
