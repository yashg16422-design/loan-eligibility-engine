"""Dead-letter consumer: an upload whose ingest crashed 3 times is marked FAILED.

The ingest handler marks a job FAILED itself on its last attempt, so only HARD crashes (a
timeout, or the database unreachable before the job was claimed) end up in the dead-letter
queue. Without this consumer such a job would show "retrying" forever. The message is the same
S3 notification the ingest queue received, so it is parsed the same way.

The operator is still told: an alarm fires whenever this function runs (serverless.yml).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any

from aws_lambda_powertools import Logger

from loan_engine.common.db import connect
from loan_engine.common.secrets import cached_db_credentials
from loan_engine.ingest import repository
from loan_engine.ingest.events import parse_sqs_record

logger = Logger(service="ingest-dlq")

REASON = "ingest crashed 3 times (timeout or database unreachable); upload the file again"


def failed_jobs(event: dict[str, Any]) -> list[uuid.UUID]:
    """The job ids inside a batch of dead-letter messages (non-upload records are skipped)."""
    jobs: list[uuid.UUID] = []
    for record in event.get("Records", []):
        jobs.extend(upload.job_id for upload in parse_sqs_record(record).uploads)
    return jobs


def mark_failed(jobs: list[uuid.UUID], fail: Callable[[uuid.UUID, str], None]) -> None:
    for job_id in jobs:
        fail(job_id, REASON)
        logger.warning("job marked FAILED from the dead-letter queue", job_id=str(job_id))


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    jobs = failed_jobs(event)
    if jobs:
        creds = cached_db_credentials(os.environ["DB_SECRET_ARN"])
        with connect(
            os.environ["DB_HOST"], "app", creds, autocommit=True, application_name="ingest-dlq"
        ) as conn:
            mark_failed(jobs, lambda job_id, reason: repository.fail_job(conn, job_id, reason))
    return {"failed": [str(j) for j in jobs]}
