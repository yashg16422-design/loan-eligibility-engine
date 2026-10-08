"""Rules for the presigned POST that lets a browser upload straight to S3.

This is the heart of the claim-check pattern: the API never receives the file, so
API Gateway's ~10 MB / ~30 s request limits don't apply. S3 enforces every rule
below itself; a browser that tampers with the form gets a 403 from S3.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from loan_engine.common.s3_keys import raw_key_for

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PRESIGN_EXPIRY_SECONDS = 600
CSV_CONTENT_TYPE = "text/csv"
_MAX_FILENAME = 255


@dataclass(frozen=True, slots=True)
class PostPolicy:
    """Inputs for boto3's generate_presigned_post."""

    key: str
    fields: dict[str, str] = field(default_factory=dict)
    conditions: list[Any] = field(default_factory=list)
    expires_in: int = PRESIGN_EXPIRY_SECONDS


def post_policy_for(job_id: uuid.UUID) -> PostPolicy:
    """The upload rules for one job.

    - key: exactly raw/<job_id>.csv (boto3 adds the key + bucket conditions itself),
      so one ticket can only ever create one specific object.
    - Content-Type pinned to text/csv; browsers may otherwise send
      application/vnd.ms-excel for .csv files.
    - content-length-range: rejects empty files and anything over 50 MB at S3.
    """
    return PostPolicy(
        key=raw_key_for(job_id),
        fields={"Content-Type": CSV_CONTENT_TYPE},
        conditions=[
            {"Content-Type": CSV_CONTENT_TYPE},
            ["content-length-range", 1, MAX_UPLOAD_BYTES],
        ],
    )


def clean_filename(raw: object) -> str | None:
    """Keep only a display name: strip any path, control characters, and cap the length.

    The filename is shown in the UI and stored for audit; it is never used as a key.
    """
    if not isinstance(raw, str):
        return None
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:_MAX_FILENAME] or None
