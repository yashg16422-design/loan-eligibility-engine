"""api Lambda: a FastAPI app behind API Gateway (HTTP API), adapted to Lambda by Mangum.

API Gateway still owns the edge (routes, throttling, the Cognito JWT authorizer); each route in
serverless.yml forwards to this one function, Mangum turns the Lambda event into an ASGI request,
and FastAPI picks the endpoint below. Interactive docs: GET /api/docs.

    GET  /                    the landing page (web/)
    GET  /upload              moved: redirects to the merchant console (/app/merchant)
    GET  /uploads             (Cognito) my bulk uploads, one record each (admins: everyone's)
    POST /uploads             (Cognito) create a job I own + presigned POST for raw/<job_id>.csv
    GET  /uploads/{job_id}    (Cognito, owner or admin) status, counts, rejects, progress
    GET  /uploads/{job_id}/emails  (Cognito, owner or admin) up to 3 emails as C sent them
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
    DELETE /uploads/{job_id}  (Cognito, owner or admin) delete that upload's users
    DELETE /uploads           (Cognito) reset my workspace; ?scope=all (admin) every account
    GET  /app, /app/{proxy}   the built dashboard (single-page app)
    GET  /{proxy}             the landing's assets (registered last: every route above wins)
"""

from __future__ import annotations

import hmac
import json
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import cache
from typing import Annotated, Any

import boto3
import psycopg
from aws_lambda_powertools import Logger
from botocore.config import Config
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from mangum import Mangum
from psycopg.pq import TransactionStatus
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

# Each upload can email up to the demo cap of users; the SES sandbox allows 200 emails a day.
MAX_UPLOADS_PER_DAY = 50
MAX_UPLOADS_PER_ACCOUNT_PER_DAY = 10  # one merchant cannot use up everyone's daily budget
# Three full 10k uploads (~780k match rows) is what the 1 GB free-plan RDS serves well; a 4th
# started swapping in testing. A new upload waits until others delete theirs.
MAX_STORED_CUSTOMERS = 30_000
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


class UploadBlockedError(ApiError):
    """The account already has an upload that is running or still holds customers."""

    status = 409

    def __init__(self, blocking: dict[str, Any]) -> None:
        name = blocking.get("filename") or "your last upload"
        stage = blocking["stage"]
        self.blocking = blocking
        super().__init__(
            f"{name} is still {stage}. Stop it or wait for it to finish, then upload again."
            if stage != "stored"
            else f"{name} still has {blocking['customers']:,} customers stored. Delete them"
            " first (its analytics are kept), then upload again."
        )


class DatabaseBusyError(ApiError):
    """The shared demo database already holds as many uploaded customers as it serves well."""

    status = 503

    def __init__(self, admin: bool) -> None:
        super().__init__(
            "The shared demo database is busy: other reviewers' uploads hold"
            f" {MAX_STORED_CUSTOMERS:,}+ customers right now."
            + (
                ' Use "Delete every account\'s uploads" in Your uploads to clear them'
                " (their charts are kept)."
                if admin
                else " Please ask them to delete their uploads once their run is done"
                " (Delete in Your uploads; their charts are kept), or try again in about"
                " 10 minutes."
            )
        )


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

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401 - APIRoute's own signature
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


@app.exception_handler(UploadBlockedError)
def upload_blocked(request: Request, err: UploadBlockedError) -> JSON:
    # The blocking upload is the caller's own, so the console can offer to clear it.
    return JSON({"error": err.message, "blocking": err.blocking}, err.status)


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
    auth_domain: str = ""
    google_sign_in: bool = False


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
        auth_domain=os.environ.get("AUTH_DOMAIN", ""),
        google_sign_in=os.environ.get("GOOGLE_SIGN_IN", "") == "true",
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


# One database connection per container, reused across requests. Opening a TLS connection is
# what a busy RDS is slowest at (a matching run writing 250k matches made new connections time
# out: seen live as 503s); a Lambda container serves one request at a time, so sharing is safe.
_CONN: psycopg.Connection | None = None
_CONN_USED_AT = 0.0
_CONN_CHECK_AFTER_S = 60  # an idle connection is pinged before use (it may have been dropped)


def _usable(conn: psycopg.Connection | None) -> bool:
    if conn is None or conn.closed or conn.broken:
        return False
    if time.monotonic() - _CONN_USED_AT < _CONN_CHECK_AFTER_S:
        return True
    try:
        conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


@contextmanager
def db(deps: Dependencies) -> Iterator[psycopg.Connection]:
    """The container's connection (autocommit; routes open their own transactions). A broken
    connection is dropped, so the next request reconnects instead of failing again."""
    global _CONN, _CONN_USED_AT
    conn = _CONN
    if conn is None or not _usable(conn):
        if conn is not None:
            with suppress(psycopg.Error):
                conn.close()
        creds = cached_db_credentials(deps.db_secret_arn)
        conn = connect(deps.db_host, "app", creds, autocommit=True, application_name="api")
        _CONN = conn
    try:
        yield conn
    except psycopg.OperationalError:
        with suppress(psycopg.Error):
            conn.close()
        _CONN = None
        raise
    finally:
        _CONN_USED_AT = time.monotonic()
        if _CONN is conn and conn.info.transaction_status != TransactionStatus.IDLE:
            with suppress(psycopg.Error):
                conn.rollback()  # never hand a half-open transaction to the next request


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


def member(
    who: Annotated[Account, Depends(signed_in)], deps: Annotated[Dependencies, Depends(get_deps)]
) -> Account:
    """The signed-in person's account: one row per verified email, however they signed in
    (password or Google), so uploads and saved checks follow the person, not the method."""
    with db(deps) as conn:
        row = repository.upsert_account(conn, who.account_id, who.email, admin=who.is_admin)
    return Account(
        account_id=str(row["account_id"]),
        email=str(row["email"]),
        is_admin=who.is_admin or bool(row.get("is_admin")),  # admin is the person's, any method
    )


# Short names for the route signatures below.
Deps = Annotated[Dependencies, Depends(get_deps)]
Body = Annotated[dict[str, Any], Depends(json_body)]
Borrower = Annotated[uuid.UUID, Depends(borrower)]
SignedIn = Annotated[Account, Depends(member)]


# ---------------------------------------------------------------- pages


@app.get("/", include_in_schema=False)
def get_home() -> Response:
    """The landing page (built into the package); without it, straight to the app."""
    file = static.resolve("", static.SITE_DIR, spa=False)
    return static.response(file) if file else RedirectResponse("/app/", status_code=302)


@app.get("/upload", include_in_schema=False)
def get_ui() -> RedirectResponse:
    """The first minimal upload page moved into the merchant console (uploads need sign-in)."""
    return RedirectResponse("/app/merchant", status_code=302)


# ---------------------------------------------------------------- bulk upload


@app.get("/uploads")
def get_uploads(who: SignedIn, deps: Deps) -> list[dict[str, Any]]:
    """My uploads as records; an admin sees every account's."""
    with db(deps) as conn:
        return repository.list_uploads(conn, None if who.is_admin else who.account_id)


def own_upload(conn: psycopg.Connection, job_id: uuid.UUID, who: Account) -> None:
    """404 unless the signed-in account owns this upload (or is an admin): other merchants'
    uploads are not even confirmed to exist."""
    exists, owner = repository.upload_owner(conn, job_id)
    if not exists or (owner != who.account_id and not who.is_admin):
        raise NotFoundError("job not found")


@app.post("/uploads", status_code=201)
def create_upload(who: SignedIn, body: Body, deps: Deps) -> dict[str, Any]:
    """Create the job row FIRST (owned by the signed-in account), then sign: S3 can only
    receive files for known jobs."""
    filename = clean_filename(body.get("filename"))
    job_id = uuid.uuid4()
    policy = post_policy_for(job_id)
    with db(deps) as conn:
        if repository.csv_uploads_last_24h(conn) >= MAX_UPLOADS_PER_DAY:
            raise TooManyChecksError
        mine = repository.csv_uploads_last_24h(conn, who.account_id)
        if not who.is_admin and mine >= MAX_UPLOADS_PER_ACCOUNT_PER_DAY:
            raise TooManyChecksError
        # One live upload per account, admins included (one shared free-tier database).
        blocking = repository.account_blocker(conn, who.account_id)
        if blocking is not None:
            raise UploadBlockedError(blocking)
        if repository.stored_csv_customers(conn) >= MAX_STORED_CUSTOMERS:
            raise DatabaseBusyError(who.is_admin)
        repository.create_job(conn, job_id, policy.key, filename, account_id=who.account_id)

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
    return {
        "job_id": str(job_id),
        "upload": {"url": post["url"], "fields": post["fields"]},
        "max_bytes": MAX_UPLOAD_BYTES,
        "expires_in": policy.expires_in,
    }


@app.get("/uploads/{job_id}")
def get_upload(job_id: uuid.UUID, who: SignedIn, deps: Deps) -> dict[str, Any]:
    with db(deps) as conn:
        own_upload(conn, job_id, who)  # rejected rows can contain personal data
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
def create_check(request: Request, body: Body, deps: Deps) -> dict[str, str]:
    """One person's check through the SAME pipeline as a bulk upload (S3 -> SQS -> ingest)."""
    user_id = uuid.uuid4()
    try:
        row = instant_check.to_user_row(body, user_id, rules_from_json(deps.validation_rules))
    except instant_check.CheckInputError as err:
        raise BadRequestError(str(err)) from None

    job_id = uuid.uuid4()
    key = raw_key_for(job_id)
    event = request.scope.get("aws.event") or {}
    source_ip = ((event.get("requestContext") or {}).get("http") or {}).get("sourceIp")
    requester = instant_check.requester_hash(source_ip, token_key(deps.token_secret_arn))
    with db(deps) as conn:
        if repository.instant_checks_last_24h(conn) >= instant_check.MAX_CHECKS_PER_DAY:
            raise TooManyChecksError
        if (
            requester
            and repository.instant_checks_last_24h(conn, requester)
            >= instant_check.MAX_CHECKS_PER_REQUESTER_PER_DAY
        ):
            raise TooManyChecksError
        # The job row first: ingest only accepts files for known jobs.
        repository.create_job(
            conn, job_id, key, "instant-check.csv", source="instant_check", requester_hash=requester
        )
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


# Analytics of a 10,000-user upload aggregate ~250k matches (seconds on a t4g.micro); the
# answer only changes when the upload is re-matched or deleted, so each container keeps it.
_ANALYTICS_CACHE: dict[tuple[uuid.UUID, tuple[Any, ...]], dict[str, Any]] = {}
_ANALYTICS_CACHE_SIZE = 32


def cached_analytics(conn: psycopg.Connection, job_id: uuid.UUID) -> dict[str, Any]:
    """repository.analytics, reused while the upload's (matched_at, purged_at) is unchanged:
    first from this container's memory, then from the database (computed once for all
    containers), and only then computed."""
    version = repository.analytics_version(conn, job_id)
    if version is None:
        return repository.analytics(conn, job_id)
    if version[1] is not None:
        # Records deleted (to keep the shared database small): keep showing the analytics
        # taken just before the delete, marked as such. Never overwrite them with zeros.
        snapshot = repository.analytics_snapshot(conn, job_id) or repository.analytics(conn, job_id)
        # The kept example emails are served by their own (owner-only) route, never here:
        # the reference dataset's analytics are public.
        charts = {k: v for k, v in snapshot.items() if k != EMAILS_KEPT}
        return {**charts, "data_deleted": True}
    key = (job_id, version)
    if key not in _ANALYTICS_CACHE:
        if len(_ANALYTICS_CACHE) >= _ANALYTICS_CACHE_SIZE:
            _ANALYTICS_CACHE.pop(next(iter(_ANALYTICS_CACHE)))  # oldest first
        stamp = "|".join(str(v) for v in version)
        stored = repository.stored_analytics(conn, job_id, stamp)
        if stored is None:
            stored = repository.analytics(conn, job_id)
            repository.store_analytics(conn, job_id, stamp, stored)
        _ANALYTICS_CACHE[key] = stored
    return _ANALYTICS_CACHE[key]


EMAILS_KEPT = "email_previews"


def snapshot_before_delete(conn: psycopg.Connection, job_id: uuid.UUID) -> None:
    """Keep an upload's charts and up to 3 of its sent emails before its records go, so the
    console still shows both afterwards. Taken once: a delete runs in several calls, and later
    calls must not overwrite it with half-deleted figures."""
    version = repository.analytics_version(conn, job_id)
    if version is None or version[1] is not None:
        return
    stamp = "|".join(str(v) for v in version)
    stored = repository.stored_analytics(conn, job_id, stamp)
    if stored is not None and EMAILS_KEPT in stored:
        return
    charts = cached_analytics(conn, job_id)
    emails = repository.email_previews(conn, job_id)
    repository.store_analytics(conn, job_id, stamp, {**charts, EMAILS_KEPT: emails})


@app.get("/analytics")
def get_analytics(deps: Deps, job_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Public: ONLY the reference dataset (the operator's full-file upload), so signed-out
    visitors see a real example. Any other upload's analytics need its owner's sign-in:
    GET /uploads/{job_id}/analytics."""
    with db(deps) as conn:
        reference = repository.reference_job(conn)
        if reference is None or (job_id is not None and job_id != reference):
            raise NotFoundError("dataset not found")
        return cached_analytics(conn, reference)


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
def get_auth_config(deps: Deps) -> dict[str, str | bool]:
    """Public identifiers only (no secret exists: the app client has none by design)."""
    return {
        "region": os.environ.get("AWS_REGION", ""),
        "user_pool_id": deps.user_pool_id,
        "client_id": deps.user_pool_client_id,
        # Managed-login domain for the OAuth code flow (Google); empty = Google not offered.
        "domain": deps.auth_domain if deps.google_sign_in else "",
        "google": deps.google_sign_in,
    }


@app.get("/account")
def get_account(who: SignedIn, deps: Deps) -> dict[str, Any]:
    with db(deps) as conn:
        account = repository.upsert_account(conn, who.account_id, who.email, admin=who.is_admin)
        account["profiles"] = repository.account_profiles(conn, who.account_id)
    account["is_admin"] = who.is_admin
    return account


@app.put("/account")
def put_account(who: SignedIn, body: Body, deps: Deps) -> dict[str, Any]:
    daily = body.get("daily_picks")
    if not isinstance(daily, bool):
        raise BadRequestError("daily_picks must be true or false")
    with db(deps) as conn:
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
    logger.info("saved checks cleared", extra=counts)
    return counts


@app.delete("/account/profiles/{user_id}")
def clear_profile(user_id: uuid.UUID, who: SignedIn, deps: Deps) -> dict[str, int]:
    """Remove one saved check."""
    with db(deps) as conn:
        return repository.clear_account_profiles(conn, who.account_id, user_id)


# ---------------------------------------------------------------- data reset (admins)


@app.delete("/uploads")
def purge_uploads(who: SignedIn, deps: Deps, scope: str = "mine") -> dict[str, int]:
    """Reset my workspace: delete the customers of every upload I made. `?scope=all` deletes
    every account's uploaded customers and needs the admin group. Instant checks stay."""
    if scope not in ("mine", "all"):
        raise BadRequestError("scope must be mine or all")
    if scope == "all" and not who.is_admin:
        raise ForbiddenError
    with db(deps) as conn:
        account = None if scope == "all" else who.account_id
        for job_id in repository.unpurged_csv_jobs(conn, account):
            snapshot_before_delete(conn, job_id)  # as a single delete does
        counts = repository.purge_csv_uploads(conn, account)
    logger.info("uploads purged", extra={"scope": scope, **counts})
    return counts


@app.post("/uploads/{job_id}/cancel")
def cancel_upload(job_id: uuid.UUID, who: SignedIn, deps: Deps) -> dict[str, str]:
    """Stop an upload (owner or admin): cancelled before loading; otherwise say what is running."""
    with db(deps) as conn:
        own_upload(conn, job_id, who)
        outcome = repository.cancel_upload(conn, job_id)
    if outcome is None:
        raise NotFoundError("job not found")
    logger.info("upload cancel requested", job_id=str(job_id), outcome=outcome)
    return {"job_id": str(job_id), "outcome": outcome}


@app.get("/uploads/{job_id}/analytics")
def get_upload_analytics(job_id: uuid.UUID, who: SignedIn, deps: Deps) -> dict[str, Any]:
    """Charts for one of my uploads (owner or admin): aggregates only."""
    with db(deps) as conn:
        own_upload(conn, job_id, who)
        return cached_analytics(conn, job_id)


@app.get("/uploads/{job_id}/emails")
def get_email_previews(job_id: uuid.UUID, who: SignedIn, deps: Deps) -> list[dict[str, Any]]:
    """Up to 3 of this upload's emails as Workflow C wrote them (owner or admin)."""
    with db(deps) as conn:
        own_upload(conn, job_id, who)
        version = repository.analytics_version(conn, job_id)
        if version is not None and version[1] is not None:
            # Records deleted: the examples kept just before the delete (none if older).
            kept = repository.analytics_snapshot(conn, job_id) or {}
            return list(kept.get(EMAILS_KEPT, []))
        return repository.email_previews(conn, job_id)


@app.delete("/uploads/{job_id}")
def purge_upload(job_id: uuid.UUID, who: SignedIn, deps: Deps) -> dict[str, Any]:
    """Delete one upload's users (owner or admin), so the file can be uploaded again as new."""
    with db(deps) as conn:
        own_upload(conn, job_id, who)
        snapshot_before_delete(conn, job_id)  # charts and example emails, before any record goes
        deleted = repository.purge_upload(conn, job_id)
        if deleted is None:
            raise NotFoundError("job not found")
        left = repository.users_left(conn, job_id)
    logger.info(
        "upload purged",
        job_id=str(job_id),
        deleted_users=deleted,
        remaining=left,
        admin=who.is_admin,
    )
    # remaining > 0: a big upload is deleted in chunks; the client calls again until 0.
    return {"job_id": str(job_id), "deleted_users": deleted, "remaining": left}


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
