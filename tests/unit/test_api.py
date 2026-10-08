"""Unit tests for the api Lambda: presign rules, derived states, routing, input checks."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from loan_engine.api import handler as api
from loan_engine.api.presign import MAX_UPLOAD_BYTES, clean_filename, post_policy_for
from loan_engine.api.status import derive_status, to_json_safe

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
        assert api.parse_json_body({"body": None}) == {}

    def test_base64_body(self):
        raw = base64.b64encode(b'{"filename": "u.csv"}').decode()
        assert api.parse_json_body({"body": raw, "isBase64Encoded": True}) == {"filename": "u.csv"}

    @pytest.mark.parametrize("body", ["not json", "[1, 2]"])
    def test_bad_body(self, body):
        with pytest.raises(api.BadRequestError):
            api.parse_json_body({"body": body})

    def test_job_id_must_be_uuid(self):
        with pytest.raises(api.BadRequestError):
            api.parse_job_id({"pathParameters": {"job_id": "../etc"}})
        assert api.parse_job_id({"pathParameters": {"job_id": str(JOB)}}) == JOB


class TestRouting:
    def call(self, event, monkeypatch):
        monkeypatch.setattr(api, "dependencies", lambda: None)
        return api.handler(event, None)

    def test_unknown_route_is_404(self, monkeypatch, lambda_context):
        res = api.handler({"routeKey": "DELETE /everything"}, lambda_context)
        assert res["statusCode"] == 404

    def test_ui_is_served_as_html(self, monkeypatch, lambda_context):
        monkeypatch.setattr(api, "dependencies", lambda: None)
        res = api.handler({"routeKey": "GET /"}, lambda_context)
        assert res["statusCode"] == 200
        assert res["headers"]["content-type"].startswith("text/html")
        assert "Loan Eligibility Engine" in res["body"]

    def test_bad_input_is_400_not_500(self, monkeypatch, lambda_context):
        monkeypatch.setattr(api, "dependencies", lambda: None)
        event = {"routeKey": "GET /uploads/{job_id}", "pathParameters": {"job_id": "nope"}}
        assert api.handler(event, lambda_context)["statusCode"] == 400

    def test_unexpected_error_is_a_generic_500(self, monkeypatch, lambda_context):
        def boom(event, deps):
            raise RuntimeError("db password is hunter2")

        monkeypatch.setattr(api, "dependencies", lambda: None)
        monkeypatch.setitem(api.ROUTES, "GET /", boom)
        res = api.handler({"routeKey": "GET /"}, lambda_context)
        assert res["statusCode"] == 500
        assert "hunter2" not in res["body"]  # internals never leak to the client


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
        monkeypatch.setattr(api, "cached_db_credentials", lambda arn: None)
        monkeypatch.setattr(api, "connect", lambda *a, **k: FakeConn())
        monkeypatch.setattr(
            api.repository,
            "create_job",
            lambda conn, job_id, key, name: created.append((job_id, key, name)),
        )

        event = {"routeKey": "POST /uploads", "body": json.dumps({"filename": "C:\\x\\users.csv"})}
        res = api.handler(event, lambda_context)

        assert res["statusCode"] == 201, res["body"]
        body = json.loads(res["body"])
        job_id = uuid.UUID(body["job_id"])
        assert created == [(job_id, f"raw/{job_id}.csv", "users.csv")]  # row BEFORE signing
        assert signed["Key"] == f"raw/{job_id}.csv"
        assert signed["Conditions"] == post_policy_for(job_id).conditions
        assert body["upload"]["url"].startswith("https://b.s3.ap-southeast-2")
