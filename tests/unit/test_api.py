"""Unit tests for the api Lambda: presign rules, derived states, routing, input checks."""

import base64
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from loan_engine.api import handler as api
from loan_engine.api.presign import MAX_UPLOAD_BYTES, clean_filename, post_policy_for
from loan_engine.api.status import derive_status, to_json_safe
from tests.unit.apigw import MERCHANT, invoke, signed_in_as

JOB = uuid.UUID("1ed10381-ea5b-4a02-8715-c0146261aa06")
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


class TestPostPolicy:
    def test_key_is_pinned_to_the_job(self):
        assert post_policy_for(JOB).key == f"raw/{JOB}.csv"

    def test_content_type_and_size_are_enforced(self):
        policy = post_policy_for(JOB)
        assert policy.fields == {"Content-Type": "text/csv"}
        assert {"Content-Type": "text/csv"} in policy.conditions
        assert ["content-length-range", 1, MAX_UPLOAD_BYTES] in policy.conditions
        assert policy.expires_in == 600


class TestCleanFilename:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("users.csv", "users.csv"),
            ("C:\\Users\\me\\users.csv", "users.csv"),  # Windows path stripped
            ("../../etc/passwd", "passwd"),
            ("bad\x00name\n.csv", "badname.csv"),  # control characters dropped
            ("", None),
            (None, None),
            (123, None),
        ],
    )
    def test_cleaning(self, raw, expected):
        assert clean_filename(raw) == expected

    def test_length_is_capped(self):
        assert len(clean_filename("a" * 1000) or "") == 255


class TestDeriveStatus:
    def test_stored_states_pass_through(self):
        for s in ("PROCESSING", "COMPLETED", "FAILED"):
            assert derive_status(s, 2, NOW - timedelta(days=1), NOW) == s

    def test_fresh_ticket_is_awaiting(self):
        assert derive_status("AWAITING_UPLOAD", 0, NOW - timedelta(minutes=5), NOW) == (
            "AWAITING_UPLOAD"
        )

    def test_never_arrived_becomes_expired(self):
        assert derive_status("AWAITING_UPLOAD", 0, NOW - timedelta(minutes=16), NOW) == "EXPIRED"

    def test_first_attempt_in_flight_is_processing_not_retrying(self):
        # Seen live: a 10,000-row upload showed "RETRYING" while its first attempt ran.
        assert derive_status("AWAITING_UPLOAD", 1, NOW - timedelta(seconds=20), NOW) == "PROCESSING"
        assert derive_status("AWAITING_UPLOAD", 2, NOW - timedelta(seconds=20), NOW) == "RETRYING"

    def test_failed_attempt_is_retrying_not_expired(self):
        # Even when old: attempts > 0 means the file arrived and SQS is retrying.
        assert derive_status("AWAITING_UPLOAD", 1, NOW - timedelta(hours=1), NOW) == "RETRYING"


def test_to_json_safe_handles_db_types():
    value = {"id": JOB, "t": NOW, "cost": Decimal("0.001234"), "rows": [(1, Decimal("2.5"))]}
    assert json.dumps(to_json_safe(value)) == (
        f'{{"id": "{JOB}", "t": "2026-10-09T12:00:00+00:00", "cost": 0.001234, "rows": [[1, 2.5]]}}'
    )


class TestRequestParsing:
    def test_empty_body_is_empty_object(self):
        assert api.parse_json(b"") == {}
        assert api.parse_json("  ") == {}

    @pytest.mark.parametrize("body", ["not json", "[1, 2]"])
    def test_bad_body(self, body):
        with pytest.raises(api.BadRequestError):
            api.parse_json(body)

    def test_base64_body_is_decoded_before_the_route(self, monkeypatch, lambda_context):
        """API Gateway may base64 a body; Mangum decodes it, so routes always see JSON."""
        seen = []
        monkeypatch.setattr(api, "dependencies", lambda: None)
        monkeypatch.setattr(api, "parse_json", lambda raw: seen.append(raw) or {})
        raw = base64.b64encode(b'{"filename": "u.csv"}').decode()
        invoke(
            {
                "routeKey": "POST /check",
                "body": raw,
                "isBase64Encoded": True,
            },
            lambda_context,
        )
        assert seen == [b'{"filename": "u.csv"}']


class TestRouting:
    def test_unknown_path_is_404_and_unknown_method_405(self, monkeypatch, lambda_context):
        monkeypatch.setattr(api, "dependencies", lambda: None)
        res = invoke({"routeKey": "GET /no/such/page"}, lambda_context)
        assert (res["statusCode"], json.loads(res["body"])) == (404, {"error": "not found"})
        res = invoke({"routeKey": "DELETE /everything"}, lambda_context)
        assert res["statusCode"] == 405 and "error" in json.loads(res["body"])

    def test_old_upload_page_moved_to_the_merchant_console(self, monkeypatch, lambda_context):
        monkeypatch.setattr(api, "dependencies", lambda: None)
        res = invoke({"routeKey": "GET /upload"}, lambda_context)
        assert res["statusCode"] == 302
        assert res["headers"]["location"] == "/app/merchant"

    @pytest.mark.parametrize(
        "event",
        [
            {
                "routeKey": "GET /uploads/{job_id}",
                "pathParameters": {"job_id": "nope"},
                "requestContext": signed_in_as(MERCHANT),
            },
            {"routeKey": "GET /analytics", "queryStringParameters": {"job_id": "nope"}},
        ],
    )
    def test_bad_input_is_400_not_500(self, monkeypatch, lambda_context, event):
        @contextmanager
        def fake_db(_deps):
            yield object()

        monkeypatch.setattr(api, "dependencies", lambda: None)
        monkeypatch.setattr(api, "db", fake_db)
        monkeypatch.setattr(
            api.repository,
            "upsert_account",
            lambda conn, sub, email, admin=False: {"account_id": sub, "email": email},
        )
        res = invoke(event, lambda_context)
        assert (res["statusCode"], json.loads(res["body"])) == (
            400,
            {"error": "job_id must be a UUID"},
        )

    def test_unexpected_error_is_a_generic_500(self, monkeypatch, lambda_context):
        def boom(*args, **kwargs):
            raise RuntimeError("db password is hunter2")

        monkeypatch.setattr(api.static, "resolve", boom)
        res = invoke({"routeKey": "GET /"}, lambda_context)
        assert res["statusCode"] == 500
        assert "hunter2" not in res["body"]  # internals never leak to the client

    def test_json_keeps_db_numbers_as_numbers(self, monkeypatch, lambda_context):
        """FastAPI's response models would write a Decimal as a string; ours must not."""

        @contextmanager
        def fake_db(_deps):
            yield object()

        monkeypatch.setattr(api, "dependencies", lambda: None)
        monkeypatch.setattr(api, "db", fake_db)
        monkeypatch.setattr(
            api.repository,
            "ops_runs",
            lambda conn: [{"run_id": JOB, "cost": Decimal("0.0012"), "at": NOW}],
        )
        res = invoke({"routeKey": "GET /ops/runs"}, lambda_context)
        assert json.loads(res["body"]) == [
            {"run_id": str(JOB), "cost": 0.0012, "at": "2026-10-09T12:00:00+00:00"}
        ]
        assert res["headers"]["cache-control"] == "no-store"


class TestCreateUploadRoute:
    """Exercises the full POST /uploads path with fakes for the DB and S3.

    Regression: a log call passed `filename=` (reserved by Python logging) and crashed
    only at runtime, so this route must be covered end to end, logging included.
    """

    def test_creates_job_then_returns_signed_post(self, monkeypatch, lambda_context):
        created: list[tuple] = []
        signed: dict = {}

        class FakeS3:
            def generate_presigned_post(self, **kwargs):
                signed.update(kwargs)
                return {
                    "url": "https://b.s3.ap-southeast-2.amazonaws.com/",
                    "fields": {"key": kwargs["Key"]},
                }

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        deps = api.Dependencies(db_host="h", db_secret_arn="arn", bucket="b", s3=FakeS3())
        monkeypatch.setattr(api, "dependencies", lambda: deps)
        monkeypatch.setattr(api, "token_key", lambda arn: b"k" * 32)
        monkeypatch.setattr(api, "cached_db_credentials", lambda arn: None)
        monkeypatch.setattr(api, "connect", lambda *a, **k: FakeConn())
        monkeypatch.setattr(
            api.repository, "csv_uploads_last_24h", lambda conn, account=None: 0
        )  # under the cap
        monkeypatch.setattr(
            api.repository,
            "upsert_account",
            lambda conn, sub, email, admin=False: {"account_id": sub, "email": email},
        )
        monkeypatch.setattr(
            api.repository,
            "create_job",
            lambda conn, job_id, key, name, account_id: created.append(
                (job_id, key, name, account_id)
            ),
        )

        event = {
            "routeKey": "POST /uploads",
            "body": json.dumps({"filename": "C:\\x\\users.csv"}),
            "requestContext": signed_in_as(MERCHANT),
        }
        assert invoke({**event, "requestContext": {}}, lambda_context)["statusCode"] == 401
        res = invoke(event, lambda_context)

        assert res["statusCode"] == 201, res["body"]
        body = json.loads(res["body"])
        job_id = uuid.UUID(body["job_id"])
        # The row exists BEFORE signing, owned by the signed-in merchant.
        assert created == [(job_id, f"raw/{job_id}.csv", "users.csv", "merchant-sub")]
        assert signed["Key"] == f"raw/{job_id}.csv"
        assert signed["Conditions"] == post_policy_for(job_id).conditions
        assert body["upload"]["url"].startswith("https://b.s3.ap-southeast-2")


class TestDatabaseBlips:
    def test_connect_is_retried_once(self, monkeypatch):
        import psycopg

        from loan_engine.common import db as dbmod
        from loan_engine.common.secrets import DbCredentials

        calls = []

        def flaky(**kwargs):
            calls.append(kwargs["host"])
            if len(calls) == 1:
                raise psycopg.errors.ConnectionTimeout("connection timeout expired")
            return "conn"

        monkeypatch.setattr(dbmod.psycopg, "connect", flaky)
        monkeypatch.setattr(dbmod, "RETRY_PAUSE_SECONDS", 0)
        assert dbmod.connect("h", "app", DbCredentials("u", "p")) == "conn"
        assert calls == ["h", "h"]

    def test_unreachable_database_is_a_503_not_a_500(self, monkeypatch, lambda_context):
        import psycopg

        def down(_deps):
            raise psycopg.errors.ConnectionTimeout("connection timeout expired")

        monkeypatch.setattr(api, "dependencies", lambda: None)
        monkeypatch.setattr(api, "db", down)
        res = invoke({"routeKey": "GET /ops/runs"}, lambda_context)
        assert res["statusCode"] == 503
        assert "try again" in json.loads(res["body"])["error"]
