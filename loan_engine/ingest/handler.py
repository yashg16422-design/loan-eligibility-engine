"""Ingest Lambda: SQS (S3 ObjectCreated) -> validate CSV -> load RDS -> notify n8n.

Flow per upload (PLAN.md §5.3):
1. Short transaction: attempts += 1 (only while AWAITING_UPLOAD).
2. Main transaction, all or nothing: claim the job (FOR UPDATE SKIP LOCKED), stream
   and validate the CSV, COPY + upsert users, save rejects, mark COMPLETED.
3. After COMMIT only: tell the next stage (best effort; the sweeper is the backstop).

Failure policy:
- Bad file (missing columns, not UTF-8) -> job FAILED immediately, no retry.
- Anything else -> re-raise so SQS redelivers; on the final delivery the job is marked
  FAILED in a separate transaction and the message is consumed.

The handler is glue only. Rules, SQL and notification are injected seams.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import Any

import boto3
import psycopg
from aws_lambda_powertools import Logger

from loan_engine.common.db import connect
from loan_engine.common.notifier import N8nWebhookNotifier, NoopNotifier, Notifier
from loan_engine.common.s3_stream import SupportsGetObject, iter_text_lines
from loan_engine.common.secrets import cached_db_credentials
from loan_engine.common.validation import (
    MissingColumnsError,
    ValidationRules,
    iter_rows,
    rules_from_json,
    scope_to_account,
    scoped_user_id,
    validate_csv,
)
from loan_engine.ingest import repository
from loan_engine.ingest.events import UploadRef, parse_sqs_record

logger = Logger(service="ingest")

# Must equal maxReceiveCount on the queue's redrive policy (serverless.yml).
MAX_RECEIVES = 3


class Outcome(StrEnum):
    """What happened to one upload; logged and returned for observability."""

    COMPLETED = "completed"
    DUPLICATE = "duplicate_or_in_flight"
    BAD_FILE = "failed_bad_file"
    POISON = "failed_after_max_retries"


@dataclass(frozen=True, slots=True)
class Dependencies:
    """Everything the handler needs from the outside world, built once per container."""

    db_host: str
    db_secret_arn: str
    db_port: int
    rules: ValidationRules
    notifier: Notifier
    s3: SupportsGetObject
    # INGEST_STREAMING=true: constant-memory path (repository.load_stream). Same results;
    # false keeps the original in-memory path (rollback switch).
    streaming: bool = False


def build_notifier(url: str, secret_arn: str) -> Notifier:
    """Pick the notifier from config: no URL -> NoopNotifier (e.g. before n8n exists)."""
    if not url:
        return NoopNotifier()
    secret = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"]
    return N8nWebhookNotifier(url, secret)


@cache
def dependencies() -> Dependencies:
    """Read config from the environment at cold start (cached for warm invocations)."""
    return Dependencies(
        db_host=os.environ["DB_HOST"],
        db_secret_arn=os.environ["DB_SECRET_ARN"],
        db_port=int(os.environ.get("DB_PORT", "5432")),
        rules=rules_from_json(os.environ.get("VALIDATION_RULES")),
        notifier=build_notifier(
            os.environ.get("N8N_WEBHOOK_URL", ""), os.environ.get("N8N_WEBHOOK_SECRET_ARN", "")
        ),
        s3=boto3.client("s3"),
        streaming=os.environ.get("INGEST_STREAMING", "false").lower() == "true",
    )


def process_upload(upload: UploadRef, receive_count: int, deps: Dependencies) -> Outcome:
    """Ingest one uploaded CSV. See the module docstring for the transaction design."""
    job_id: uuid.UUID = upload.job_id
    creds = cached_db_credentials(deps.db_secret_arn)

    # autocommit=True + explicit transaction() blocks = real BEGIN/COMMIT per block.
    with connect(
        deps.db_host,
        "app",
        creds,
        port=deps.db_port,
        autocommit=True,
        application_name="ingest",
    ) as conn:
        repository.bump_attempts(conn, job_id)
        try:
            with conn.transaction():
                if not repository.claim_job(conn, job_id):
                    return Outcome.DUPLICATE
                load = _load_streaming if deps.streaming else _load_in_memory
                if load(conn, upload, deps) is Outcome.BAD_FILE:
                    return Outcome.BAD_FILE
        except Exception as err:
            if receive_count < MAX_RECEIVES:
                logger.exception("ingest attempt failed; SQS will redeliver", attempt=receive_count)
                raise
            # Final delivery: record the failure in its own transaction, consume the message.
            with conn.transaction():
                repository.fail_job(
                    conn, job_id, f"ingest failed after {receive_count} tries: {err}"
                )
            logger.exception("ingest failed permanently", attempt=receive_count)
            return Outcome.POISON

    # Only after COMMIT: never announce data that might still roll back.
    deps.notifier.notify_job_completed(job_id)
    return Outcome.COMPLETED


def _bad_file(conn: psycopg.Connection, job_id: uuid.UUID, err: Exception) -> Outcome:
    """The file itself is unusable (missing columns, not UTF-8): retrying can't help."""
    reason = str(err) if isinstance(err, MissingColumnsError) else "not UTF-8"
    repository.fail_job(conn, job_id, f"bad file: {reason}")
    logger.warning("job failed: bad file", reason=reason)
    return Outcome.BAD_FILE


def _load_in_memory(conn: psycopg.Connection, upload: UploadRef, deps: Dependencies) -> Outcome:
    """The original path: validate the whole file in memory, then COPY + upsert."""
    job_id = upload.job_id
    try:
        lines = iter_text_lines(deps.s3, upload.bucket, upload.key)
        result = validate_csv(lines, deps.rules)
    except (MissingColumnsError, UnicodeDecodeError) as err:
        return _bad_file(conn, job_id, err)

    # An owned upload's customers belong to that account: same file, fresh rows.
    owner = repository.job_account(conn, job_id)
    valid = scope_to_account(result.valid, owner) if owner else result.valid
    counts = repository.load_users(conn, job_id, valid)
    repository.save_rejects(conn, job_id, result.rejects)
    return _complete(conn, job_id, result.total_rows, counts, len(result.rejects))


def _load_streaming(conn: psycopg.Connection, upload: UploadRef, deps: Dependencies) -> Outcome:
    """Constant memory: rows go from the S3 stream through COPY into Postgres as they are
    read (repository.load_stream). Same counts, rejects and users as the in-memory path."""
    job_id = upload.job_id
    owner = repository.job_account(conn, job_id)
    scope = (lambda user_id: scoped_user_id(user_id, owner)) if owner else None
    try:
        # A savepoint: a decode error halfway through the COPY rolls back only the staging,
        # so the job can still be marked FAILED in this transaction.
        with conn.transaction():
            rows = iter_rows(iter_text_lines(deps.s3, upload.bucket, upload.key), deps.rules)
            load = repository.load_stream(conn, job_id, rows, scope)
    except (MissingColumnsError, UnicodeDecodeError) as err:
        return _bad_file(conn, job_id, err)
    return _complete(conn, job_id, load.total_rows, load.counts, load.rejected)


def _complete(
    conn: psycopg.Connection,
    job_id: uuid.UUID,
    total_rows: int,
    counts: repository.LoadCounts,
    rejected: int,
) -> Outcome:
    repository.complete_job(conn, job_id, total_rows=total_rows, counts=counts, rejected=rejected)
    logger.info(
        "job completed",
        total_rows=total_rows,
        inserted=counts.inserted,
        updated=counts.updated,
        unchanged=counts.unchanged,
        rejected=rejected,
    )
    return Outcome.COMPLETED


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Process every SQS record and every S3 record inside it."""
    deps = dependencies()
    outcomes: dict[str, str] = {}
    for record in event.get("Records", []):
        message = parse_sqs_record(record)
        for reason in message.skipped:
            logger.info("skipped S3 record", reason=reason, message_id=message.message_id)
        for upload in message.uploads:
            logger.append_keys(job_id=str(upload.job_id))
            outcome = process_upload(upload, message.receive_count, deps)
            logger.info("upload processed", outcome=outcome.value, attempt=message.receive_count)
            outcomes[str(upload.job_id)] = outcome
    return {"outcomes": outcomes}
