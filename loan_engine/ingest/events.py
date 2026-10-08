"""Parse the SQS -> S3 event envelope into the uploads the ingest Lambda must process.

Pure functions: given the Lambda event dict, return plain data. All the AWS envelope
quirks (s3:TestEvent, several records per message, URL-encoded keys) live here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from loan_engine.common.s3_keys import job_id_from_event_key


@dataclass(frozen=True, slots=True)
class UploadRef:
    """One uploaded object to ingest."""

    bucket: str
    key: str  # decoded key, e.g. raw/<job_id>.csv
    job_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """The uploads found in one SQS message, plus what we skipped and why."""

    message_id: str
    receive_count: int
    uploads: list[UploadRef]
    skipped: list[str]  # human-readable reasons, for the logs


def parse_sqs_record(record: dict[str, Any]) -> ParsedMessage:
    """Turn one SQS record (whose body is an S3 notification) into UploadRefs.

    - `s3:TestEvent` (sent once when the notification is configured) -> no uploads.
    - Every S3 record in the body is examined, not just the first.
    - Keys that are not exactly raw/<uuid>.csv are skipped and never reach the DB.
    """
    message_id = record.get("messageId", "?")
    receive_count = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
    body = json.loads(record["body"])

    if body.get("Event") == "s3:TestEvent":
        return ParsedMessage(message_id, receive_count, [], ["s3:TestEvent"])

    uploads: list[UploadRef] = []
    skipped: list[str] = []
    for s3_record in body.get("Records", []):
        event_name = s3_record.get("eventName", "")
        raw_key = s3_record.get("s3", {}).get("object", {}).get("key", "")
        bucket = s3_record.get("s3", {}).get("bucket", {}).get("name", "")
        if not event_name.startswith("ObjectCreated:"):
            skipped.append(f"ignored event {event_name!r}")
            continue
        job_id = job_id_from_event_key(raw_key)
        if job_id is None or not bucket:
            skipped.append(f"key does not match raw/<uuid>.csv: {raw_key!r}")
            continue
        uploads.append(UploadRef(bucket=bucket, key=f"raw/{job_id}.csv", job_id=job_id))
    return ParsedMessage(message_id, receive_count, uploads, skipped)
