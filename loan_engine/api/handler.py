"""api Lambda behind the HTTP API: serves the upload page and the upload/status JSON.

Routes (a table, so adding one is a one-line change):
    GET  /                    -> the single-page upload UI (same origin = no API CORS)
    POST /uploads             -> create a job + presigned POST for raw/<job_id>.csv
    GET  /uploads/{job_id}    -> status, counts, rejects, match/notify progress
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from botocore.config import Config

from loan_engine.api import repository
from loan_engine.api.presign import MAX_UPLOAD_BYTES, clean_filename, post_policy_for
from loan_engine.api.status import derive_status, to_json_safe
from loan_engine.common.db import connect
from loan_engine.common.secrets import cached_db_credentials

logger = Logger(service="api")

UI_HTML = (Path(__file__).with_name("ui.html")).read_text(encoding="utf-8")
Response = dict[str, Any]


class BadRequestError(Exception):
    """The client sent something invalid; becomes an HTTP 400."""


@dataclass(frozen=True, slots=True)
class Dependencies:
    """Config + clients, built once per container."""

    db_host: str
    db_secret_arn: str
    bucket: str
    s3: Any


@cache
def dependencies() -> Dependencies:
    region = os.environ["AWS_REGION"]
    return Dependencies(
        db_host=os.environ["DB_HOST"],
        db_secret_arn=os.environ["DB_SECRET_ARN"],
        bucket=os.environ["DATA_BUCKET"],
        # Regional virtual-hosted endpoint: the browser POSTs to
        # https://<bucket>.s3.<region>.amazonaws.com directly. The global endpoint can
        # answer a new bucket with a 307 redirect, which breaks a CORS upload.
        s3=boto3.client(
            "s3",
            region_name=region,
            endpoint_url=f"https://s3.{region}.amazonaws.com",
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        ),
    )


# ---------------------------------------------------------------- responses


def json_response(status: int, body: object) -> Response:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(to_json_safe(body)),
    }


def html_response(html: str) -> Response:
    return {
        "statusCode": 200,
        "headers": {
            "content-type": "text/html; charset=utf-8",
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
        },
        "body": html,
    }


def parse_json_body(event: dict[str, Any]) -> dict[str, Any]:
    """Decode the (possibly base64) request body; an empty body means {}."""
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise BadRequestError("body must be JSON") from None
    if not isinstance(body, dict):
        raise BadRequestError("body must be a JSON object")
    return body


def parse_job_id(event: dict[str, Any]) -> uuid.UUID:
    raw = (event.get("pathParameters") or {}).get("job_id", "")
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise BadRequestError("job_id must be a UUID") from None


# ---------------------------------------------------------------- routes


def get_ui(event: dict[str, Any], deps: Dependencies) -> Response:
    return html_response(UI_HTML)


def create_upload(event: dict[str, Any], deps: Dependencies) -> Response:
    """Create the job row FIRST, then sign: S3 can only receive files for known jobs."""
    filename = clean_filename(parse_json_body(event).get("filename"))
    job_id = uuid.uuid4()
    policy = post_policy_for(job_id)

    creds = cached_db_credentials(deps.db_secret_arn)
    with connect(deps.db_host, "app", creds, autocommit=True, application_name="api") as conn:
        repository.create_job(conn, job_id, policy.key, filename)

    # Local signing with the Lambda role's credentials: no network call.
    post = deps.s3.generate_presigned_post(
        Bucket=deps.bucket,
        Key=policy.key,
        Fields=policy.fields,
        Conditions=policy.conditions,
        ExpiresIn=policy.expires_in,
    )
    # Not `filename=`: that name is reserved by Python logging (LogRecord.filename).
    logger.info("upload ticket created", job_id=str(job_id), upload_filename=filename)
    return json_response(
        201,
        {
            "job_id": str(job_id),
            "upload": {"url": post["url"], "fields": post["fields"]},
            "max_bytes": MAX_UPLOAD_BYTES,
            "expires_in": policy.expires_in,
        },
    )


def get_upload(event: dict[str, Any], deps: Dependencies) -> Response:
    job_id = parse_job_id(event)
    creds = cached_db_credentials(deps.db_secret_arn)
    with connect(deps.db_host, "app", creds, autocommit=True, application_name="api") as conn:
        progress = repository.get_job_progress(conn, job_id)
    if progress is None:
        return json_response(404, {"error": "job not found"})

    job = progress["job"]
    job["status"] = derive_status(
        job["status"], job["attempts"], job["created_at"], job.pop("db_now")
    )
    return json_response(200, progress)


ROUTES: dict[str, Callable[[dict[str, Any], Dependencies], Response]] = {
    "GET /": get_ui,
    "POST /uploads": create_upload,
    "GET /uploads/{job_id}": get_upload,
}


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict[str, Any], context: object) -> Response:
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return json_response(404, {"error": "not found"})
    try:
        return route(event, dependencies())
    except BadRequestError as err:
        return json_response(400, {"error": str(err)})
    except Exception:
        # Log the detail, return nothing internal to the client.
        logger.exception("unhandled error")
        return json_response(500, {"error": "internal error"})
