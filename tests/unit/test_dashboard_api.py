"""Unit tests for the borrower-dashboard API: tokens, instant check, preferences, static, routes."""

import json
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from loan_engine.api import handler as api
from loan_engine.api import instant_check, static, tokens
from loan_engine.api.preferences import PreferencesError, parse_preferences
from loan_engine.common.validation import DEFAULT_RULES, validate_csv

KEY = b"k" * 32
USER = uuid.UUID("33f22eb9-6487-4c15-8e43-5ff59be31a9b")
NOW = 1_800_000_000
ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- tokens


class TestTokens:
    def test_round_trip(self):
        assert tokens.verify(tokens.sign(USER, NOW + 60, KEY), KEY, NOW) == USER

    def test_expired(self):
        with pytest.raises(tokens.InvalidTokenError, match="expired"):
            tokens.verify(tokens.sign(USER, NOW, KEY), KEY, NOW)

    def test_tampered_user_or_expiry_is_rejected(self):
        token = tokens.sign(USER, NOW + 60, KEY)
        other = uuid.uuid4().hex
        for forged in (other + token[32:], token.replace(str(NOW + 60), str(NOW + 10**6))):
            with pytest.raises(tokens.InvalidTokenError, match="signature"):
                tokens.verify(forged, KEY, NOW)

    def test_wrong_key(self):
        with pytest.raises(tokens.InvalidTokenError):
            tokens.verify(tokens.sign(USER, NOW + 60, KEY), b"x" * 32, NOW)

    @pytest.mark.parametrize("junk", ["", "a.b", "a.b.c", "x" * 300, None, 42])
    def test_malformed(self, junk):
        with pytest.raises(tokens.InvalidTokenError):
            tokens.verify(junk, KEY, NOW)

    def test_short_key_refused(self):
        with pytest.raises(ValueError, match="32 bytes"):
            tokens.sign(USER, NOW, b"short")

    def test_bearer_header(self):
        assert tokens.bearer({"authorization": "Bearer abc"}) == "abc"
        assert tokens.bearer({"authorization": "Basic abc"}) == ""
        assert tokens.bearer(None) == ""


# ---------------------------------------------------------------- instant check


CHECK_BODY = {
    "monthly_income": 48000,
    "credit_score": "742",
    "employment_status": "salaried",
    "age": 29,
}


class TestInstantCheck:
    def test_valid_body_becomes_a_csv_the_ingest_validator_accepts(self):
        row = instant_check.to_user_row({**CHECK_BODY, "name": 'Ana, "A"'}, USER, DEFAULT_RULES)
        result = validate_csv(instant_check.to_csv(row).decode().splitlines(), DEFAULT_RULES)
        assert len(result.valid) == 1 and not result.rejects
        assert result.valid[0].name == 'Ana, "A"'  # quoted correctly by the csv module

    def test_never_a_real_email(self):
        row = instant_check.to_user_row(CHECK_BODY, USER, DEFAULT_RULES)
        assert row.email.endswith("@example.invalid")

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("credit_score", 950, "between 300 and 900"),
            ("age", 12, "between 18 and 100"),
            ("monthly_income", "lots", "whole number"),
            ("employment_status", "astronaut", "salaried, self-employed or business"),
        ],
    )
    def test_invalid_input_gives_a_friendly_message(self, field, value, message):
        with pytest.raises(instant_check.CheckInputError, match=message):
            instant_check.to_user_row({**CHECK_BODY, field: value}, USER, DEFAULT_RULES)

    def test_self_employed_underscore_form_accepted(self):
        body = {**CHECK_BODY, "employment_status": "self_employed"}
        row = instant_check.to_user_row(body, USER, DEFAULT_RULES)
        assert row.employment_status.value == "self_employed"

    def test_name_is_cleaned(self):
        assert instant_check.clean_name("A\x00b\n" + "c" * 100) == "Ab" + "c" * 58
        assert instant_check.clean_name(None) == ""


# ---------------------------------------------------------------- preferences


class TestPreferences:
    A, B, C, D = (str(uuid.uuid4()) for _ in range(4))

    def test_top3_must_be_in_shortlist_and_hidden_wins(self):
        prefs = parse_preferences(
            {"shortlist": [self.A, self.B, self.B], "top3": [self.A, self.C], "hidden": [self.B]}
        )
        assert prefs["shortlist"] == [uuid.UUID(self.A)]  # B hidden, duplicate dropped
        assert prefs["top3"] == [uuid.UUID(self.A)]  # C was never shortlisted
        assert prefs["alerts"] is False

    def test_limits_and_types(self):
        with pytest.raises(PreferencesError, match="at most 3"):
            parse_preferences({"top3": [self.A, self.B, self.C, self.D]})
        with pytest.raises(PreferencesError, match="invalid product id"):
            parse_preferences({"shortlist": ["nope"]})
        with pytest.raises(PreferencesError, match="true or false"):
            parse_preferences({"alerts": "yes"})


# ---------------------------------------------------------------- static files


class TestStatic:
    @pytest.fixture
    def root(self, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "index.html").write_text("<!doctype html>")
        (tmp_path / "assets" / "app-1a2b.js").write_text("console.log(1)")
        (tmp_path / "logo.png").write_bytes(b"\x89PNG")
        return tmp_path

    def test_spa_routes_fall_back_to_index(self, root):
        for path in ("", "dashboard", "ops/runs"):
            assert static.resolve(path, root).path.name == "index.html"

    def test_hashed_assets_are_immutable(self, root):
        assert static.resolve("assets/app-1a2b.js", root).immutable
        assert not static.resolve("", root).immutable

    @pytest.mark.parametrize("bad", ["../secret.py", "assets/../../x.js", ".env", "a/.git/x.js"])
    def test_traversal_and_hidden_files_refused(self, root, bad):
        assert static.resolve(bad, root) is None

    def test_unknown_types_and_missing_files(self, root):
        assert static.resolve("handler.py", root) is None
        assert static.resolve("assets/missing.js", root) is None

    def test_binary_is_base64(self, root):
        res = static.response(static.resolve("logo.png", root))
        assert res["isBase64Encoded"] is True
        assert res["headers"]["content-type"] == "image/png"


# ---------------------------------------------------------------- routes


@pytest.fixture
def deps(monkeypatch):
    class FakeS3:
        def __init__(self):
            self.puts = []

        def put_object(self, **kwargs):
            self.puts.append(kwargs)

    d = api.Dependencies(
        db_host="h", db_secret_arn="a", bucket="b", s3=FakeS3(), token_secret_arn="t"
    )

    @contextmanager
    def fake_db(_deps):
        yield object()

    monkeypatch.setattr(api, "dependencies", lambda: d)
    monkeypatch.setattr(api, "db", fake_db)
    monkeypatch.setattr(api, "token_key", lambda arn: KEY)
    return d


def call(route, lambda_context, body=None, token=None):
    event = {"routeKey": route, "headers": {}}
    if body is not None:
        event["body"] = json.dumps(body)
    if token:
        event["headers"]["authorization"] = f"Bearer {token}"
    res = api.handler(event, lambda_context)
    return res["statusCode"], json.loads(res["body"])


class TestCheckRoute:
    def test_queues_a_job_and_returns_a_token(self, deps, monkeypatch, lambda_context):
        jobs = []
        monkeypatch.setattr(api.repository, "instant_checks_last_24h", lambda conn: 0)
        monkeypatch.setattr(api.repository, "create_job", lambda *a, **k: jobs.append((a, k)))
        status, body = call("POST /check", lambda_context, CHECK_BODY)
        assert status == 201
        assert tokens.verify(body["token"], KEY, int(time.time())) == uuid.UUID(body["user_id"])
        assert jobs[0][1] == {"source": "instant_check"}
        put = deps.s3.puts[0]
        assert put["Key"] == f"raw/{body['job_id']}.csv"  # the same key a CSV upload uses
        assert body["user_id"].encode() in put["Body"]

    def test_daily_cap(self, deps, monkeypatch, lambda_context):
        monkeypatch.setattr(api.repository, "instant_checks_last_24h", lambda conn: 10**6)
        status, _ = call("POST /check", lambda_context, CHECK_BODY)
        assert status == 429
        assert deps.s3.puts == []

    def test_bad_input_is_400_and_nothing_is_written(self, deps, lambda_context):
        status, body = call("POST /check", lambda_context, {**CHECK_BODY, "age": 7})
        assert status == 400 and "18" in body["error"]
        assert deps.s3.puts == []


class TestMeRoutes:
    def test_no_or_bad_token_is_401(self, deps, lambda_context):
        assert call("GET /me", lambda_context)[0] == 401
        assert call("GET /me/matches", lambda_context, token="a.b.c")[0] == 401

    def test_queued_before_ingest(self, deps, monkeypatch, lambda_context):
        monkeypatch.setattr(api.repository, "get_me", lambda conn, uid: None)
        token = tokens.sign(USER, 2**40, KEY)
        assert call("GET /me", lambda_context, token=token) == (202, {"matching": "queued"})

    @pytest.mark.parametrize(
        ("job", "match", "expected"),
        [
            (None, None, "running"),
            ("COMPLETED", "RUNNING", "running"),
            ("COMPLETED", "DONE", "done"),
            ("FAILED", None, "failed"),
            ("COMPLETED", "FAILED", "failed"),
        ],
    )
    def test_matching_state(self, job, match, expected):
        assert api.matching_state(job, match) == expected

    def test_preferences_saved_for_the_token_owner(self, deps, monkeypatch, lambda_context):
        saved = {}
        monkeypatch.setattr(api.repository, "get_me", lambda conn, uid: {"user_id": uid})
        monkeypatch.setattr(
            api.repository, "save_preferences", lambda conn, uid, p: saved.update(uid=uid, **p) or p
        )
        token = tokens.sign(USER, 2**40, KEY)
        status, _ = call("PUT /me/preferences", lambda_context, {"alerts": True}, token=token)
        assert status == 200 and saved["uid"] == USER and saved["alerts"] is True


def test_every_route_is_wired_in_serverless_yml():
    """A route in the code but not in serverless.yml would silently 404 in production."""
    events = set(re.findall(r"- httpApi: (\S+ \S+)", (ROOT / "serverless.yml").read_text()))
    assert set(api.ROUTES) == events
