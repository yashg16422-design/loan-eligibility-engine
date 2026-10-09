"""api Lambda behind the HTTP API: upload flow, borrower dashboard API, ops view, static app.

Routes (a table, so adding one is a one-line change):
    GET  /                    -> the single-page upload UI (same origin = no API CORS)
    POST /uploads             -> create a job + presigned POST for raw/<job_id>.csv
    GET  /uploads/{job_id}    -> status, counts, rejects, match/notify progress
    POST /check               -> instant check: 4 numbers -> the real pipeline -> a token
    GET  /me                  -> (bearer token) profile, matching state, headline numbers
    GET  /me/matches          -> (bearer token) active matches with product details
    GET|PUT /me/preferences   -> (bearer token) shortlist, top 3, hidden, alerts
    GET  /products            -> active products + compiled rules (what-if simulator)
    GET  /ops/runs|crawl|errors -> aggregates for the operator view (no personal data)
    GET  /app, /app/{proxy+}  -> the built dashboard (single-page app)
    POST /internal/email-tokens -> (X-Webhook-Secret) signed "view my matches" links for
                                 Workflow C's emails; the HMAC key never leaves AWS
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import boto3
import psycopg
from aws_lambda_powertools import Logger
from botocore.config import Config

from loan_engine.api import instant_check, repository, static, tokens
from loan_engine.api.preferences import PreferencesError, parse_preferences
from loan_engine.api.presign import MAX_UPLOAD_BYTES, clean_filename, post_policy_for
from loan_engine.api.status import derive_status, to_json_safe
from loan_engine.common.db import connect
from loan_engine.common.s3_keys import raw_key_for
from loan_engine.common.secrets import cached_db_credentials
from loan_engine.common.validation import rules_from_json

logger = Logger(service="api")

UI_HTML = (Path(__file__).with_name("ui.html")).read_text(encoding="utf-8")
Response = dict[str, Any]


class BadRequestError(Exception):
    """The client sent something invalid; becomes an HTTP 400."""


class UnauthorizedError(Exception):
    """Missing, forged or expired dashboard token; becomes an HTTP 401."""


class TooManyChecksError(Exception):
    """The daily instant-check budget is used up; becomes an HTTP 429."""


@dataclass(frozen=True, slots=True)
class Dependencies:
    """Config + clients, built once per container."""

    db_host: str
    db_secret_arn: str
    bucket: str
    s3: Any
    token_secret_arn: str = ""
    webhook_secret_arn: str = ""
    compile_prompt_version: str = "compile_v1"
    validation_rules: str = ""


@cache
def dependencies() -> Dependencies:
    region = os.environ["AWS_REGION"]
    return Dependencies(
        db_host=os.environ["DB_HOST"],
        db_secret_arn=os.environ["DB_SECRET_ARN"],
        bucket=os.environ["DATA_BUCKET"],
        token_secret_arn=os.environ.get("TOKEN_SECRET_ARN", ""),
        webhook_secret_arn=os.environ.get("N8N_WEBHOOK_SECRET_ARN", ""),
        compile_prompt_version=os.environ.get("COMPILE_PROMPT_VERSION", "compile_v1"),
        validation_rules=os.environ.get("VALIDATION_RULES", ""),
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


# ---------------------------------------------------------------- dashboard


@cache
def token_key(secret_arn: str) -> bytes:
    """The HMAC key from Secrets Manager, fetched once per container."""
    client = boto3.client("secretsmanager", region_name=os.environ["AWS_REGION"])
    return client.get_secret_value(SecretId=secret_arn)["SecretString"].encode()


def authenticated_user(event: dict[str, Any], deps: Dependencies) -> uuid.UUID:
    try:
        return tokens.verify(
            tokens.bearer(event.get("headers")), token_key(deps.token_secret_arn), int(time.time())
        )
    except tokens.InvalidTokenError as err:
        logger.info("rejected dashboard token", reason=str(err))
        raise UnauthorizedError from None


def db(deps: Dependencies) -> psycopg.Connection:
    creds = cached_db_credentials(deps.db_secret_arn)
    return connect(deps.db_host, "app", creds, autocommit=True, application_name="api")


def create_check(event: dict[str, Any], deps: Dependencies) -> Response:
    """One person's check through the SAME pipeline as a bulk upload (S3 -> SQS -> ingest)."""
    user_id = uuid.uuid4()
    try:
        row = instant_check.to_user_row(
            parse_json_body(event), user_id, rules_from_json(deps.validation_rules)
        )
    except instant_check.CheckInputError as err:
        raise BadRequestError(str(err)) from None

    job_id = uuid.uuid4()
    key = raw_key_for(job_id)
    with db(deps) as conn:
        if repository.instant_checks_last_24h(conn) >= instant_check.MAX_CHECKS_PER_DAY:
            raise TooManyChecksError
        # The job row first: ingest only accepts files for known jobs.
        repository.create_job(conn, job_id, key, "instant-check.csv", source="instant_check")
    deps.s3.put_object(
        Bucket=deps.bucket, Key=key, Body=instant_check.to_csv(row), ContentType="text/csv"
    )
    token = tokens.sign(
        user_id, int(time.time()) + tokens.CHECK_TTL_SECONDS, token_key(deps.token_secret_arn)
    )
    logger.info("instant check queued", job_id=str(job_id))
    return json_response(201, {"token": token, "user_id": str(user_id), "job_id": str(job_id)})


def matching_state(job_status: str | None, match_status: str | None) -> str:
    """One word for the UI: running until Workflow B has written this user's matches."""
    if job_status == "FAILED" or match_status == "FAILED":
        return "failed"
    return "done" if match_status == "DONE" else "running"


def get_me(event: dict[str, Any], deps: Dependencies) -> Response:
    user_id = authenticated_user(event, deps)
    with db(deps) as conn:
        me = repository.get_me(conn, user_id)
    if me is None:  # instant check still in the queue: the ingest Lambda hasn't loaded it yet
        return json_response(202, {"matching": "queued"})
    me["matching"] = matching_state(me.pop("job_status"), me.pop("match_status"))
    return json_response(200, me)


def get_my_matches(event: dict[str, Any], deps: Dependencies) -> Response:
    user_id = authenticated_user(event, deps)
    with db(deps) as conn:
        return json_response(200, repository.get_matches(conn, user_id))


def get_my_preferences(event: dict[str, Any], deps: Dependencies) -> Response:
    user_id = authenticated_user(event, deps)
    with db(deps) as conn:
        return json_response(200, repository.get_preferences(conn, user_id))


def put_my_preferences(event: dict[str, Any], deps: Dependencies) -> Response:
    user_id = authenticated_user(event, deps)
    try:
        prefs = parse_preferences(parse_json_body(event))
    except PreferencesError as err:
        raise BadRequestError(str(err)) from None
    with db(deps) as conn:
        if repository.get_me(conn, user_id) is None:
            raise BadRequestError("your profile is still being loaded")
        return json_response(200, repository.save_preferences(conn, user_id, prefs))


def get_products(event: dict[str, Any], deps: Dependencies) -> Response:
    with db(deps) as conn:
        return json_response(200, repository.get_products(conn, deps.compile_prompt_version))


def get_ops_runs(event: dict[str, Any], deps: Dependencies) -> Response:
    with db(deps) as conn:
        return json_response(200, repository.ops_runs(conn))


def get_ops_crawl(event: dict[str, Any], deps: Dependencies) -> Response:
    with db(deps) as conn:
        return json_response(200, repository.ops_crawl(conn))


def get_ops_errors(event: dict[str, Any], deps: Dependencies) -> Response:
    with db(deps) as conn:
        return json_response(200, repository.ops_errors(conn))


MAX_EMAIL_TOKENS = 50  # Workflow C sends at most a handful per run (SES sandbox)


def create_email_tokens(event: dict[str, Any], deps: Dependencies) -> Response:
    """Sign 14-day dashboard links for the users Workflow C is about to email.

    Called by n8n with the same shared secret that guards the ingest webhook (one secret,
    one Header Auth credential). Signing here keeps the HMAC key out of n8n entirely.
    """
    sent = (event.get("headers") or {}).get("x-webhook-secret", "")
    expected = token_key(deps.webhook_secret_arn).decode()
    if not sent or not hmac.compare_digest(sent.encode(), expected.encode()):
        logger.warning("email-token request with a wrong or missing secret")
        raise UnauthorizedError
    raw = parse_json_body(event).get("user_ids")
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_EMAIL_TOKENS:
        raise BadRequestError(f"user_ids must be a list of 1-{MAX_EMAIL_TOKENS} ids")
    try:
        users = [uuid.UUID(str(u)) for u in raw]
    except ValueError:
        raise BadRequestError("user_ids contains an invalid id") from None
    key = token_key(deps.token_secret_arn)
    expires = int(time.time()) + tokens.EMAIL_TTL_SECONDS
    logger.info("email tokens signed", count=len(users))
    return json_response(200, {"tokens": {str(u): tokens.sign(u, expires, key) for u in users}})


def get_app(event: dict[str, Any], deps: Dependencies) -> Response:
    file = static.resolve((event.get("pathParameters") or {}).get("proxy", ""))
    if file is None:
        return json_response(404, {"error": "not found"})
    return static.response(file)


ROUTES: dict[str, Callable[[dict[str, Any], Dependencies], Response]] = {
    "GET /": get_ui,
    "POST /uploads": create_upload,
    "GET /uploads/{job_id}": get_upload,
    "POST /check": create_check,
    "GET /me": get_me,
    "GET /me/matches": get_my_matches,
    "GET /me/preferences": get_my_preferences,
    "PUT /me/preferences": put_my_preferences,
    "GET /products": get_products,
    "GET /ops/runs": get_ops_runs,
    "GET /ops/crawl": get_ops_crawl,
    "GET /ops/errors": get_ops_errors,
    "GET /app": get_app,
    "GET /app/{proxy+}": get_app,
    "POST /internal/email-tokens": create_email_tokens,
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
    except UnauthorizedError:
        return json_response(401, {"error": "sign-in link is invalid or expired"})
    except TooManyChecksError:
        return json_response(429, {"error": "daily demo limit reached, try again tomorrow"})
    except Exception:
        # Log the detail, return nothing internal to the client.
        logger.exception("unhandled error")
        return json_response(500, {"error": "internal error"})
