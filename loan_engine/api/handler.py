"""api Lambda: a FastAPI app behind API Gateway (HTTP API), adapted to Lambda by Mangum.

API Gateway still owns the edge (routes, throttling, the Cognito JWT authorizer); each route in
serverless.yml forwards to this one function, Mangum turns the Lambda event into an ASGI request,
and FastAPI picks the endpoint below. Interactive docs: GET /api/docs.

    GET  /                    the landing page (web/), or the upload UI if not built
    GET  /upload              the minimal upload UI (same origin = no API CORS)
    GET  /uploads             recent bulk uploads, one record each (counts only)
    POST /uploads             create a job + presigned POST + this browser's delete key
    GET  /uploads/{job_id}    status, counts, rejects, match/notify progress
    DELETE /uploads/{job_id}/users  (X-Upload-Key) the uploader deletes its own upload's users
    POST /check               instant check: 4 numbers -> the real pipeline -> a token
    GET  /me, /me/matches     (dashboard token) profile, matching state, matches
    GET|PUT /me/preferences   (dashboard token) shortlist, top 3, hidden, alerts
    GET  /products            active products + compiled rules (what-if simulator)
    GET  /ops/runs|crawl|errors  aggregates for the operator view (no personal data)
    POST /internal/email-tokens  (X-Webhook-Secret) signed links for Workflow C's emails
    GET  /analytics           distributions for one upload (?job_id=) or all users
    GET  /auth/config         public Cognito ids the browser needs to sign in
    GET|PUT /account          (Cognito) the account + its saved profiles / settings
    POST /account/profiles[/{user_id}/open]  (Cognito) save a check / reopen it
    DELETE /me                (dashboard token) delete my own instant check
    DELETE /account/profiles[/{user_id}]     (Cognito) remove saved checks; account stays
    DELETE /uploads[/{job_id}]               (Cognito `admin` group) delete uploaded users
    GET  /app, /app/{proxy}   the built dashboard (single-page app)
    GET  /{proxy}             the landing's assets (registered last: every route above wins)
"""

from __future__ import annotations

import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Annotated, Any

import boto3
import psycopg
from aws_lambda_powertools import Logger
from botocore.config import Config
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.routing import APIRoute
from mangum import Mangum
from starlette.exceptions import HTTPException

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

# Each upload can email up to the demo cap of users; the SES sandbox allows 200 emails a day.
MAX_UPLOADS_PER_DAY = 50
MAX_EMAIL_TOKENS = 50  # Workflow C sends at most a handful per run (SES sandbox)
ADMIN_GROUP = "admin"  # a Cognito user pool group (serverless.yml AdminGroup)


# ---------------------------------------------------------------- errors -> HTTP


class ApiError(Exception):
    """An expected failure with a client-safe message; becomes {"error": message}."""

    status = 400
    message = "bad request"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class BadRequestError(ApiError):
    """The client sent something invalid."""


class UnauthorizedError(ApiError):
    """Missing, forged or expired token."""

    status, message = 401, "please sign in again"


class ForbiddenError(ApiError):
    """Signed in, but not allowed (not in the `admin` group)."""

    status, message = 403, "only an admin can do that"


class NotFoundError(ApiError):
    status, message = 404, "not found"


class ConflictError(ApiError):
    status, message = 409, "conflict"


class TooManyChecksError(ApiError):
    """A daily budget (instant checks or CSV uploads) is used up."""

    status, message = 429, "the daily demo limit is reached; try again tomorrow"


class JSON(JSONResponse):
    """Every API response: DB types made JSON-safe, never cached by the browser or a proxy."""

    def __init__(self, content: object, status_code: int = 200, **kwargs: object) -> None:
        # FastAPI passes background= (and could pass headers=); ours are merged in, not lost
        headers = {"cache-control": "no-store", **(kwargs.pop("headers", None) or {})}  # type: ignore[dict-item]
        super().__init__(content, status_code, headers=headers, **kwargs)  # type: ignore[arg-type]

    def render(self, content: object) -> bytes:
        return json.dumps(to_json_safe(content)).encode()


class PlainRoute(APIRoute):
    """Routes whose return type is documentation only.

    By default FastAPI turns a return annotation into a response model, and pydantic writes a
    database Decimal (an interest rate, a cost) as the STRING "10.50". Without the model, the
    JSON class above writes it as the number 10.5, exactly as before.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs["response_model"] = None
        super().__init__(*args, **kwargs)


app = FastAPI(
    title="ClickPar Match API",
    summary="Loan Eligibility Engine: uploads, matching results, accounts",
    default_response_class=JSON,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.router.route_class = PlainRoute


@app.exception_handler(ApiError)
def api_error(request: Request, err: ApiError) -> JSON:
    return JSON({"error": err.message}, err.status)


@app.exception_handler(repository.JobBusyError)
def job_busy(request: Request, err: repository.JobBusyError) -> JSON:
    return JSON(
        {"error": "that upload is still loading, matching or emailing; try again soon"}, 409
    )


@app.exception_handler(psycopg.OperationalError)
def database_unavailable(request: Request, err: psycopg.OperationalError) -> JSON:
    """The database could not be reached even after a retry: temporary, so say so (503)."""
    logger.warning("database unavailable", error=type(err).__name__)
    return JSON({"error": "the database is briefly unavailable; try again in a moment"}, 503)


@app.exception_handler(RequestValidationError)
def invalid_input(request: Request, err: RequestValidationError) -> JSON:
    """A path or query value FastAPI could not parse (e.g. a job id that is not a UUID)."""
    where = err.errors()[0].get("loc", ())
    return JSON(
        {"error": f"{where[-1]} must be a UUID" if len(where) > 1 else "invalid input"}, 400
    )


@app.exception_handler(HTTPException)
def http_error(request: Request, err: HTTPException) -> JSON:
    """Unknown path (404) or method (405), in the same {"error": ...} shape as everything else."""
    return JSON(
        {"error": "not found" if err.status_code == 404 else str(err.detail).lower()},
        err.status_code,
    )


@app.exception_handler(Exception)
def unexpected(request: Request, err: Exception) -> JSON:
    # Log the detail, return nothing internal to the client.
    logger.exception("unhandled error")
    return JSON({"error": "internal error"}, 500)


# ---------------------------------------------------------------- dependencies


@dataclass(frozen=True, slots=True)
class Dependencies:
    """Config + clients, built once per container."""

    db_host: str
    db_secret_arn: str
    bucket: str
    s3: Any
    token_secret_arn: str = ""
    webhook_secret_arn: str = ""
    user_pool_id: str = ""
    user_pool_client_id: str = ""
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
        user_pool_id=os.environ.get("USER_POOL_ID", ""),
        user_pool_client_id=os.environ.get("USER_POOL_CLIENT_ID", ""),
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


def get_deps() -> Dependencies:
    return dependencies()  # looked up at call time, so tests can swap it


@cache
def token_key(secret_arn: str) -> bytes:
    """An HMAC key from Secrets Manager, fetched once per container."""
    client = boto3.client("secretsmanager", region_name=os.environ["AWS_REGION"])
    return client.get_secret_value(SecretId=secret_arn)["SecretString"].encode()


def db(deps: Dependencies) -> psycopg.Connection:
    creds = cached_db_credentials(deps.db_secret_arn)
    return connect(deps.db_host, "app", creds, autocommit=True, application_name="api")


def parse_json(raw: bytes | str) -> dict[str, Any]:
    """The request body as a JSON object; an empty body means {}."""
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    if not text.strip():
        return {}
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        raise BadRequestError("body must be JSON") from None
    if not isinstance(body, dict):
        raise BadRequestError("body must be a JSON object")
    return body


async def json_body(request: Request) -> dict[str, Any]:
    return parse_json(await request.body())  # Mangum already decoded a base64 body


def borrower(request: Request, deps: Annotated[Dependencies, Depends(get_deps)]) -> uuid.UUID:
    """The user behind a dashboard link (HMAC token in `Authorization: Bearer`)."""
    try:
        return tokens.verify(
            tokens.bearer(dict(request.headers)), token_key(deps.token_secret_arn), int(time.time())
        )
    except tokens.InvalidTokenError as err:
        logger.info("rejected dashboard token", reason=str(err))
        raise UnauthorizedError from None


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    email: str
    is_admin: bool = False


def cognito_groups(raw: object) -> set[str]:
    """`cognito:groups` as a set. API Gateway's JWT authorizer passes a list claim as the
    string "[a b]"; a raw list is accepted too."""
    if isinstance(raw, list):
        return {str(g) for g in raw}
    if isinstance(raw, str):
        return set(raw.strip("[]").replace(",", " ").split())
    return set()


def signed_in(request: Request) -> Account:
    """The Cognito identity API Gateway's JWT authorizer already verified.

    Checked again here (defence in depth): an ID token with a verified email is required, so
    an access token or an unverified sign-up can never create or read an account.
    """
    event = request.scope.get("aws.event") or {}
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get(
        "claims"
    ) or {}
    verified = str(claims.get("email_verified", "")).lower() == "true"
    if claims.get("token_use") != "id" or not claims.get("sub") or not verified:
        raise UnauthorizedError
    return Account(
        account_id=str(claims["sub"]),
        email=str(claims.get("email", "")),
        is_admin=ADMIN_GROUP in cognito_groups(claims.get("cognito:groups")),
    )


def admin(who: Annotated[Account, Depends(signed_in)]) -> Account:
    if not who.is_admin:
        raise ForbiddenError
    return who


# Short names for the route signatures below.
Deps = Annotated[Dependencies, Depends(get_deps)]
Body = Annotated[dict[str, Any], Depends(json_body)]
Borrower = Annotated[uuid.UUID, Depends(borrower)]
SignedIn = Annotated[Account, Depends(signed_in)]
Admin = Annotated[Account, Depends(admin)]


# ---------------------------------------------------------------- pages


def html(page: str) -> HTMLResponse:
    return HTMLResponse(
        page,
        headers={
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
        },
    )


@app.get("/", include_in_schema=False)
def get_home() -> Response:
    """The landing page when it is built into the package, else the minimal upload page."""
    file = static.resolve("", static.SITE_DIR, spa=False)
    return static.response(file) if file else html(UI_HTML)


@app.get("/upload", include_in_schema=False)
def get_ui() -> HTMLResponse:
    """The original minimal upload page (the assignment's required UI), kept at /upload."""
    return html(UI_HTML)


# ---------------------------------------------------------------- bulk upload


def upload_key(deps: Dependencies) -> bytes:
    """Signs the delete key handed to the browser that created an upload."""
    return tokens.derived_key(token_key(deps.token_secret_arn), b"upload-owner")


@app.get("/uploads")
def get_uploads(deps: Deps) -> list[dict[str, Any]]:
    with db(deps) as conn:
        return repository.list_uploads(conn)


@app.post("/uploads", status_code=201)
def create_upload(body: Body, deps: Deps) -> dict[str, Any]:
    """Create the job row FIRST, then sign: S3 can only receive files for known jobs."""
    filename = clean_filename(body.get("filename"))
    job_id = uuid.uuid4()
    policy = post_policy_for(job_id)
    with db(deps) as conn:
        if repository.csv_uploads_last_24h(conn) >= MAX_UPLOADS_PER_DAY:
            raise TooManyChecksError
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
    # Whoever holds this key (the uploading browser) may delete this upload's users later.
    delete_key = tokens.sign(
        job_id, int(time.time()) + tokens.UPLOAD_KEY_TTL_SECONDS, upload_key(deps)
    )
    return {
        "job_id": str(job_id),
        "upload": {"url": post["url"], "fields": post["fields"]},
        "max_bytes": MAX_UPLOAD_BYTES,
        "expires_in": policy.expires_in,
        "delete_key": delete_key,
    }


@app.get("/uploads/{job_id}")
def get_upload(job_id: uuid.UUID, deps: Deps) -> dict[str, Any]:
    with db(deps) as conn:
        progress = repository.get_job_progress(conn, job_id)
    if progress is None:
        raise NotFoundError("job not found")
    job = progress["job"]
    job["status"] = derive_status(
        job["status"], job["attempts"], job["created_at"], job.pop("db_now")
    )
    return progress


# ---------------------------------------------------------------- borrower dashboard


@app.post("/check", status_code=201)
def create_check(body: Body, deps: Deps) -> dict[str, str]:
    """One person's check through the SAME pipeline as a bulk upload (S3 -> SQS -> ingest)."""
    user_id = uuid.uuid4()
    try:
        row = instant_check.to_user_row(body, user_id, rules_from_json(deps.validation_rules))
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
    return {"token": token, "user_id": str(user_id), "job_id": str(job_id)}


def matching_state(job_status: str | None, match_status: str | None) -> str:
    """One word for the UI: running until Workflow B has written this user's matches."""
    if job_status == "FAILED" or match_status == "FAILED":
        return "failed"
    return "done" if match_status == "DONE" else "running"


@app.get("/me")
def get_me(user_id: Borrower, deps: Deps) -> dict[str, Any] | JSON:
    with db(deps) as conn:
        me = repository.get_me(conn, user_id)
    if me is None:  # instant check still in the queue: the ingest Lambda hasn't loaded it yet
        return JSON({"matching": "queued"}, 202)
    me["matching"] = matching_state(me.pop("job_status"), me.pop("match_status"))
    return me


@app.get("/me/matches")
def get_my_matches(user_id: Borrower, deps: Deps) -> list[dict[str, Any]]:
    with db(deps) as conn:
        return repository.get_matches(conn, user_id)


@app.get("/me/preferences")
def get_my_preferences(user_id: Borrower, deps: Deps) -> dict[str, Any]:
    with db(deps) as conn:
        return repository.get_preferences(conn, user_id)


@app.put("/me/preferences")
def put_my_preferences(user_id: Borrower, body: Body, deps: Deps) -> dict[str, Any]:
    try:
        prefs = parse_preferences(body)
    except PreferencesError as err:
        raise BadRequestError(str(err)) from None
    with db(deps) as conn:
        if repository.get_me(conn, user_id) is None:
            raise BadRequestError("your profile is still being loaded")
        return repository.save_preferences(conn, user_id, prefs)


@app.delete("/me")
def delete_me(user_id: Borrower, deps: Deps) -> dict[str, str]:
    """Delete the instant check behind a dashboard link: its matches and emails go with it."""
    with db(deps) as conn:
        outcome = repository.delete_check(conn, user_id)
    logger.info("check delete", outcome=outcome)
    if outcome == "csv_user":
        raise ConflictError("this profile came from a bulk upload; only an admin can delete it")
    if outcome == "busy":
        raise ConflictError("your results email is still being sent; try again in two minutes")
    return {"outcome": outcome}


# ---------------------------------------------------------------- catalogue + operator view


@app.get("/products")
def get_products(deps: Deps) -> list[dict[str, Any]]:
    with db(deps) as conn:
        return repository.get_products(conn, deps.compile_prompt_version)


@app.get("/ops/runs")
def get_ops_runs(deps: Deps) -> list[dict[str, Any]]:
    with db(deps) as conn:
        return repository.ops_runs(conn)


@app.get("/ops/crawl")
def get_ops_crawl(deps: Deps) -> dict[str, Any]:
    with db(deps) as conn:
        return repository.ops_crawl(conn)


@app.get("/ops/errors")
def get_ops_errors(deps: Deps) -> list[dict[str, Any]]:
    with db(deps) as conn:
        return repository.ops_errors(conn)


@app.get("/analytics")
def get_analytics(deps: Deps, job_id: uuid.UUID | None = None) -> dict[str, Any]:
    with db(deps) as conn:
        return repository.analytics(conn, job_id)


@app.post("/internal/email-tokens")
def create_email_tokens(request: Request, body: Body, deps: Deps) -> dict[str, Any]:
    """Sign 14-day dashboard links for the users Workflow C is about to email.

    Called by n8n with the same shared secret that guards the ingest webhook (one secret,
    one Header Auth credential). Signing here keeps the HMAC key out of n8n entirely.
    """
    sent = request.headers.get("x-webhook-secret", "")
    expected = token_key(deps.webhook_secret_arn).decode()
    if not sent or not hmac.compare_digest(sent.encode(), expected.encode()):
        logger.warning("email-token request with a wrong or missing secret")
        raise UnauthorizedError
    raw = body.get("user_ids")
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_EMAIL_TOKENS:
        raise BadRequestError(f"user_ids must be a list of 1-{MAX_EMAIL_TOKENS} ids")
    try:
        users = [uuid.UUID(str(u)) for u in raw]
    except ValueError:
        raise BadRequestError("user_ids contains an invalid id") from None
    # Only users Workflow C is about to email get a link: even with the shared secret, nobody
    # can mint dashboard access for an arbitrary user id.
    with db(deps) as conn:
        allowed = repository.awaiting_notification(conn, users)
    key = token_key(deps.token_secret_arn)
    expires = int(time.time()) + tokens.EMAIL_TTL_SECONDS
    logger.info("email tokens signed", count=len(allowed), refused=len(set(users) - allowed))
    return {"tokens": {str(u): tokens.sign(u, expires, key) for u in users if u in allowed}}


# ---------------------------------------------------------------- accounts (Cognito)


@app.get("/auth/config")
def get_auth_config(deps: Deps) -> dict[str, str]:
    """Public identifiers only (no secret exists: the app client has none by design)."""
    return {
        "region": os.environ.get("AWS_REGION", ""),
        "user_pool_id": deps.user_pool_id,
        "client_id": deps.user_pool_client_id,
    }


@app.get("/account")
def get_account(who: SignedIn, deps: Deps) -> dict[str, Any]:
    with db(deps) as conn:
        account = repository.upsert_account(conn, who.account_id, who.email)
        account["profiles"] = repository.account_profiles(conn, who.account_id)
    account["is_admin"] = who.is_admin
    return account


@app.put("/account")
def put_account(who: SignedIn, body: Body, deps: Deps) -> dict[str, Any]:
    daily = body.get("daily_picks")
    if not isinstance(daily, bool):
        raise BadRequestError("daily_picks must be true or false")
    with db(deps) as conn:
        repository.upsert_account(conn, who.account_id, who.email)
        repository.set_daily_picks(conn, who.account_id, daily)
    return get_account(who, deps)


SAVE_MESSAGES = {
    "saved": (200, "Saved to your account."),
    "already_saved": (200, "Already saved to your account."),
    "taken": (409, "This check is already saved to another account."),
    "not_found": (409, "Your check is still being processed. Try again in a few seconds."),
}


@app.post("/account/profiles")
def save_profile(who: SignedIn, body: Body, deps: Deps) -> JSON:
    """Attach the check behind a dashboard link to the signed-in account.

    Holding a valid dashboard link proves the person ran (or was emailed) that check.
    """
    try:
        user_id = tokens.verify(
            str(body.get("token", "")), token_key(deps.token_secret_arn), int(time.time())
        )
    except tokens.InvalidTokenError:
        raise BadRequestError("that results link is invalid or expired; run a new check") from None
    with db(deps) as conn:
        repository.upsert_account(conn, who.account_id, who.email)
        outcome = repository.claim_profile(conn, who.account_id, user_id)
    status, message = SAVE_MESSAGES[outcome]
    logger.info("profile save", outcome=outcome)
    return JSON({"outcome": outcome, "message": message, "user_id": str(user_id)}, status)


@app.post("/account/profiles/{user_id}/open")
def open_profile(user_id: uuid.UUID, who: SignedIn, deps: Deps) -> dict[str, str]:
    """A fresh 24 h dashboard link for a profile this account owns (any device, any day)."""
    with db(deps) as conn:
        if not repository.owns_profile(conn, who.account_id, user_id):
            raise NotFoundError("not one of your saved checks")
    token = tokens.sign(
        user_id, int(time.time()) + tokens.CHECK_TTL_SECONDS, token_key(deps.token_secret_arn)
    )
    return {"token": token}


@app.delete("/account/profiles")
def clear_profiles(who: SignedIn, deps: Deps) -> dict[str, int]:
    """Start fresh: remove every saved check. The account and its settings stay."""
    with db(deps) as conn:
        counts = repository.clear_account_profiles(conn, who.account_id)
    logger.info("saved checks cleared", **counts)
    return counts


@app.delete("/account/profiles/{user_id}")
def clear_profile(user_id: uuid.UUID, who: SignedIn, deps: Deps) -> dict[str, int]:
    """Remove one saved check."""
    with db(deps) as conn:
        return repository.clear_account_profiles(conn, who.account_id, user_id)


# ---------------------------------------------------------------- data reset (admins)


@app.delete("/uploads")
def purge_all_uploads(who: Admin, deps: Deps) -> dict[str, int]:
    """Delete every user that came from a CSV upload (instant checks stay)."""
    with db(deps) as conn:
        counts = repository.purge_csv_uploads(conn)
    logger.info("all uploads purged", **counts)
    return counts


def purge(job_id: uuid.UUID, deps: Dependencies, by: str) -> dict[str, Any]:
    """Delete one upload's users so the same file can be uploaded again as a new record."""
    with db(deps) as conn:
        deleted = repository.purge_upload(conn, job_id)
    if deleted is None:
        raise NotFoundError("job not found")
    logger.info("upload purged", job_id=str(job_id), deleted_users=deleted, by=by)
    return {"job_id": str(job_id), "deleted_users": deleted}


@app.delete("/uploads/{job_id}")
def purge_upload(job_id: uuid.UUID, who: Admin, deps: Deps) -> dict[str, Any]:
    """Admin: delete any upload's users."""
    return purge(job_id, deps, by="admin")


@app.delete("/uploads/{job_id}/users")
def purge_my_upload(job_id: uuid.UUID, request: Request, deps: Deps) -> dict[str, Any]:
    """The uploader deletes its own upload, proven by the delete key POST /uploads returned."""
    try:
        owner = tokens.verify(
            request.headers.get("x-upload-key", ""), upload_key(deps), int(time.time())
        )
    except tokens.InvalidTokenError:
        owner = None
    if owner != job_id:
        raise ForbiddenError("only the browser that uploaded this file (or an admin) can delete it")
    return purge(job_id, deps, by="uploader")


# ---------------------------------------------------------------- built front ends (last)


@app.get("/app", include_in_schema=False)
@app.get("/app/{proxy:path}", include_in_schema=False)
def get_app(proxy: str = "") -> Response:
    file = static.resolve(proxy, static.STATIC_DIR)
    if file is None:
        raise NotFoundError
    return static.response(file)


@app.get("/{proxy:path}", include_in_schema=False)
def get_site(proxy: str) -> Response:
    """The landing's assets. Registered last, so it only sees paths no route above matched."""
    file = static.resolve(proxy, static.SITE_DIR, spa=False)
    if file is None:
        raise NotFoundError
    return static.response(file)


# ---------------------------------------------------------------- Lambda entry point

_asgi = Mangum(app, lifespan="off")


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    return _asgi(event, context)  # type: ignore[arg-type]
