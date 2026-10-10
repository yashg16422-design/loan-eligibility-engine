"""Unit tests for the borrower-dashboard API: tokens, instant check, preferences, static, routes."""

import json
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.routing import APIRoute

from loan_engine.api import handler as api
from loan_engine.api import instant_check, static, tokens
from loan_engine.api.preferences import PreferencesError, parse_preferences
from loan_engine.common.validation import DEFAULT_RULES, validate_csv
from tests.unit.apigw import ADMIN, MERCHANT, invoke, signed_in_as

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

    def test_binary_is_base64_through_the_lambda(self, root, monkeypatch, lambda_context):
        monkeypatch.setattr(static, "STATIC_DIR", root)
        monkeypatch.setattr(api, "dependencies", lambda: None)
        res = invoke({"routeKey": "GET /app/{proxy+}", "pathParameters": {"proxy": "logo.png"}})
        assert res["isBase64Encoded"] is True and res["body"] == "iVBORw=="
        assert res["headers"]["content-type"] == "image/png"
        page = invoke({"routeKey": "GET /app/{proxy+}", "pathParameters": {"proxy": "dashboard"}})
        assert page["body"] == "<!doctype html>"  # client-side route -> index.html
        assert page["headers"]["cache-control"] == "no-cache"
        asset = invoke(
            {"routeKey": "GET /app/{proxy+}", "pathParameters": {"proxy": "assets/app-1a2b.js"}}
        )
        assert "immutable" in asset["headers"]["cache-control"]


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
    # Every signed-in route resolves the account row first (one per verified email).
    monkeypatch.setattr(
        api.repository,
        "upsert_account",
        lambda conn, sub, email, admin=False: {"account_id": sub, "email": email},
    )
    return d


def call(route, lambda_context, body=None, token=None):
    event = {"routeKey": route, "headers": {}}
    if body is not None:
        event["body"] = json.dumps(body)
    if token:
        event["headers"]["authorization"] = f"Bearer {token}"
    res = invoke(event, lambda_context)
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


def route_keys() -> set[str]:
    """Every FastAPI endpoint as an API Gateway route key ("{proxy:path}" is "{proxy+}")."""
    return {
        f"{m} {r.path.replace(':path}', '+}')}"
        for r in api.app.routes
        if isinstance(r, APIRoute)
        for m in r.methods
    }


def test_every_route_is_wired_in_serverless_yml():
    """A route in the code but not in serverless.yml would silently 404 in production."""
    text = (ROOT / "serverless.yml").read_text()
    events = set(re.findall(r"- httpApi: (\S+ \S+)", text))
    # Object form (routes with an authorizer): method + path on the next lines.
    events |= {f"{m} {p}" for m, p in re.findall(r"method: (\S+)\n\s+path: (\S+)", text)}
    assert route_keys() == events


def test_account_routes_require_the_cognito_authorizer():
    text = (ROOT / "serverless.yml").read_text()
    guarded = re.findall(r"method: (\S+)\n\s+path: (\S+)\n\s+authorizer: \{ name: cognito \}", text)
    # Accounts, and every bulk-upload route (uploads belong to a signed-in merchant).
    expected = {r for r in route_keys() if " /account" in r or " /uploads" in r}
    assert {f"{m} {p}" for m, p in guarded} == expected


class TestEmailTokens:
    SECRET = "s" * 48

    @pytest.fixture
    def secrets(self, deps, monkeypatch):
        keys = {"t": KEY, "w": self.SECRET.encode()}
        monkeypatch.setattr(api, "token_key", lambda arn: keys[arn])
        monkeypatch.setattr(
            api,
            "dependencies",
            lambda: api.Dependencies(
                db_host="h",
                db_secret_arn="a",
                bucket="b",
                s3=None,
                token_secret_arn="t",
                webhook_secret_arn="w",
            ),
        )

    def post(self, lambda_context, body, secret):
        event = {"routeKey": "POST /internal/email-tokens", "headers": {}, "body": json.dumps(body)}
        if secret is not None:
            event["headers"]["x-webhook-secret"] = secret
        res = invoke(event, lambda_context)
        return res["statusCode"], json.loads(res["body"])

    def test_signs_one_link_per_user_valid_for_two_weeks(
        self, secrets, monkeypatch, lambda_context
    ):
        monkeypatch.setattr(api.repository, "awaiting_notification", lambda conn, ids: set(ids))
        status, body = self.post(lambda_context, {"user_ids": [str(USER)]}, self.SECRET)
        assert status == 200
        token = body["tokens"][str(USER)]
        now = int(time.time())
        assert tokens.verify(token, KEY, now + 13 * 24 * 3600) == USER
        with pytest.raises(tokens.InvalidTokenError, match="expired"):
            tokens.verify(token, KEY, now + 15 * 24 * 3600)

    @pytest.mark.parametrize("secret", [None, "", "wrong", "s" * 47])
    def test_wrong_or_missing_secret_is_401(self, secrets, lambda_context, secret):
        assert self.post(lambda_context, {"user_ids": [str(USER)]}, secret)[0] == 401

    @pytest.mark.parametrize("ids", [[], ["nope"], [str(USER)] * 51, "x"])
    def test_bad_body_is_400(self, secrets, lambda_context, ids):
        assert self.post(lambda_context, {"user_ids": ids}, self.SECRET)[0] == 400


class TestAccounts:
    CLAIMS: ClassVar[dict[str, str]] = {
        "sub": "c0ffee-sub",
        "email": "aarav@example.org",
        "email_verified": "true",
        "token_use": "id",
    }

    def event(self, route, claims=None, body=None, path=None):
        e = {
            "routeKey": route,
            "headers": {},
            "requestContext": {"authorizer": {"jwt": {"claims": claims or {}}}},
        }
        if body is not None:
            e["body"] = json.dumps(body)
        if path:
            e["pathParameters"] = path
        return e

    @pytest.mark.parametrize(
        "claims",
        [
            {},
            {**CLAIMS, "token_use": "access"},
            {**CLAIMS, "email_verified": "false"},
            {**CLAIMS, "sub": ""},
        ],
    )
    def test_only_a_verified_id_token_is_accepted(self, deps, lambda_context, claims):
        res = invoke(self.event("GET /account", claims), lambda_context)
        assert res["statusCode"] == 401

    @pytest.mark.parametrize(
        ("outcome", "status"),
        [("saved", 200), ("already_saved", 200), ("taken", 409), ("not_found", 409)],
    )
    def test_save_profile_needs_a_genuine_results_link(
        self, deps, monkeypatch, lambda_context, outcome, status
    ):
        seen = {}
        monkeypatch.setattr(
            api.repository,
            "upsert_account",
            lambda conn, sub, email, admin=False: {"account_id": sub, "email": email},
        )
        monkeypatch.setattr(
            api.repository,
            "claim_profile",
            lambda conn, sub, uid: seen.update(sub=sub, uid=uid) or outcome,
        )
        token = tokens.sign(USER, int(time.time()) + 60, KEY)
        res = invoke(
            self.event("POST /account/profiles", self.CLAIMS, {"token": token}), lambda_context
        )
        assert res["statusCode"] == status
        assert seen == {
            "sub": "c0ffee-sub",
            "uid": USER,
        }  # the profile goes to the signed-in account

    def test_forged_results_link_is_refused(self, deps, lambda_context):
        res = invoke(
            self.event("POST /account/profiles", self.CLAIMS, {"token": "a.b.c"}), lambda_context
        )
        assert res["statusCode"] == 400

    def test_open_only_your_own_profile(self, deps, monkeypatch, lambda_context):
        monkeypatch.setattr(api.repository, "owns_profile", lambda conn, sub, uid: uid == USER)
        ok = invoke(
            self.event(
                "POST /account/profiles/{user_id}/open", self.CLAIMS, path={"user_id": str(USER)}
            ),
            lambda_context,
        )
        assert ok["statusCode"] == 200
        assert tokens.verify(json.loads(ok["body"])["token"], KEY, int(time.time())) == USER
        other = invoke(
            self.event(
                "POST /account/profiles/{user_id}/open",
                self.CLAIMS,
                path={"user_id": str(uuid.uuid4())},
            ),
            lambda_context,
        )
        assert other["statusCode"] == 404

    def test_auth_config_exposes_public_ids_only(self, deps, monkeypatch, lambda_context):
        monkeypatch.setattr(
            api,
            "dependencies",
            lambda: api.Dependencies(
                db_host="h",
                db_secret_arn="a",
                bucket="b",
                s3=None,
                user_pool_id="pool",
                user_pool_client_id="client",
            ),
        )
        body = json.loads(invoke({"routeKey": "GET /auth/config"}, lambda_context)["body"])
        assert set(body) == {"region", "user_pool_id", "client_id", "domain", "google"}


class TestSite:
    def test_landing_has_no_spa_fallback(self, tmp_path):
        (tmp_path / "index.html").write_text("<!doctype html>")
        (tmp_path / "geo").mkdir()
        (tmp_path / "geo" / "globe.json").write_text("{}")
        assert static.resolve("", tmp_path, spa=False).path.name == "index.html"
        assert (
            static.resolve("geo/globe.json", tmp_path, spa=False).content_type == "application/json"
        )
        assert static.resolve("dashboard", tmp_path, spa=False) is None  # not silently the landing
        assert static.resolve("../handler.py", tmp_path, spa=False) is None

    def test_home_goes_to_the_app_when_the_landing_is_not_built(self, monkeypatch, lambda_context):
        monkeypatch.setattr(api, "dependencies", lambda: None)
        monkeypatch.setattr(static, "SITE_DIR", Path("/nonexistent"))
        res = invoke({"routeKey": "GET /"}, lambda_context)
        assert (res["statusCode"], res["headers"]["location"]) == (302, "/app/")


def test_email_tokens_only_for_users_about_to_be_emailed(deps, monkeypatch, lambda_context):
    other = uuid.uuid4()
    monkeypatch.setattr(api, "token_key", lambda arn: KEY if arn == "t" else b"s" * 48)
    monkeypatch.setattr(
        api,
        "dependencies",
        lambda: api.Dependencies(
            db_host="h",
            db_secret_arn="a",
            bucket="b",
            s3=None,
            token_secret_arn="t",
            webhook_secret_arn="w",
        ),
    )
    monkeypatch.setattr(api.repository, "awaiting_notification", lambda conn, ids: {USER})
    event = {
        "routeKey": "POST /internal/email-tokens",
        "headers": {"x-webhook-secret": "s" * 48},
        "body": json.dumps({"user_ids": [str(USER), str(other)]}),
    }
    body = json.loads(invoke(event, lambda_context)["body"])
    assert set(body["tokens"]) == {str(USER)}  # the arbitrary id gets nothing


def test_upload_tickets_have_a_daily_cap(deps, monkeypatch, lambda_context):
    monkeypatch.setattr(api, "connect", lambda *a, **k: contextmanager(lambda: (yield object()))())
    monkeypatch.setattr(api, "cached_db_credentials", lambda arn: None)
    monkeypatch.setattr(
        api.repository, "csv_uploads_last_24h", lambda conn: api.MAX_UPLOADS_PER_DAY
    )
    res = invoke(
        {
            "routeKey": "POST /uploads",
            "body": json.dumps({"filename": "u.csv"}),
            "requestContext": signed_in_as(MERCHANT),
        },
        lambda_context,
    )
    assert res["statusCode"] == 429


# ---------------------------------------------------------------- data reset


class TestDataReset:
    CLAIMS: ClassVar[dict[str, str]] = TestAccounts.CLAIMS
    ADMIN: ClassVar[dict[str, str]] = {**TestAccounts.CLAIMS, "cognito:groups": "[admin]"}
    JOB = uuid.UUID("0b7f9c1e-2a51-4f6e-9d3c-3f5d8a1c2b4e")

    event = TestAccounts.event

    @pytest.mark.parametrize(
        ("raw", "groups"),
        [
            ("[admin]", {"admin"}),
            ("[ops admin]", {"ops", "admin"}),
            (["admin"], {"admin"}),
            ("", set()),
            (None, set()),
        ],
    )
    def test_cognito_groups_claim(self, raw, groups):
        assert api.cognito_groups(raw) == groups

    def test_owner_or_admin_deletes_an_upload_and_only_admins_delete_all(
        self, deps, monkeypatch, lambda_context
    ):
        purged = []
        owners = {self.JOB: "merchant-sub"}
        monkeypatch.setattr(
            api.repository, "upload_owner", lambda conn, j: (j in owners, owners.get(j))
        )
        monkeypatch.setattr(api.repository, "purge_upload", lambda conn, j: purged.append(j) or 7)
        monkeypatch.setattr(
            api.repository,
            "purge_csv_uploads",
            lambda conn, account=None: purged.append(account or "all")
            or {"deleted_users": 9, "uploads": 2},
        )
        one = {"routeKey": "DELETE /uploads/{job_id}", "pathParameters": {"job_id": str(self.JOB)}}
        other = {**MERCHANT, "sub": "someone-else"}
        # Another merchant cannot delete it, or even learn that it exists.
        res = invoke({**one, "requestContext": signed_in_as(other)}, lambda_context)
        assert res["statusCode"] == 404 and purged == []
        for who in (MERCHANT, ADMIN):  # the owner, and an admin
            res = invoke({**one, "requestContext": signed_in_as(who)}, lambda_context)
            assert (res["statusCode"], json.loads(res["body"])["deleted_users"]) == (200, 7)
        every = {"routeKey": "DELETE /uploads", "queryStringParameters": {"scope": "all"}}
        assert invoke({**every, "requestContext": signed_in_as(MERCHANT)})["statusCode"] == 403
        res = invoke({**every, "requestContext": signed_in_as(ADMIN)}, lambda_context)
        assert json.loads(res["body"]) == {"deleted_users": 9, "uploads": 2}
        # Any merchant may reset its OWN workspace (no scope = mine).
        mine = {"routeKey": "DELETE /uploads", "requestContext": signed_in_as(MERCHANT)}
        assert invoke(mine, lambda_context)["statusCode"] == 200
        assert purged == [self.JOB, self.JOB, "all", "merchant-sub"]

    def test_purge_of_a_missing_or_busy_job(self, deps, monkeypatch, lambda_context):
        event = {
            "routeKey": "DELETE /uploads/{job_id}",
            "pathParameters": {"job_id": str(self.JOB)},
            "requestContext": signed_in_as(ADMIN),
        }
        monkeypatch.setattr(api.repository, "upload_owner", lambda conn, j: (False, None))
        assert invoke(event, lambda_context)["statusCode"] == 404

        def busy(conn, job):
            raise api.repository.JobBusyError

        monkeypatch.setattr(api.repository, "upload_owner", lambda conn, j: (True, None))
        monkeypatch.setattr(api.repository, "purge_upload", busy)
        assert invoke(event, lambda_context)["statusCode"] == 409

    def test_account_says_whether_it_is_an_admin(self, deps, monkeypatch, lambda_context):
        monkeypatch.setattr(
            api.repository,
            "upsert_account",
            lambda conn, sub, email, admin=False: {"account_id": sub, "email": email},
        )
        monkeypatch.setattr(api.repository, "account_profiles", lambda conn, sub: [])
        for claims, admin in ((self.CLAIMS, False), (self.ADMIN, True)):
            res = invoke(self.event("GET /account", claims), lambda_context)
            assert json.loads(res["body"])["is_admin"] is admin

    @pytest.mark.parametrize(
        ("outcome", "status"),
        [("deleted", 200), ("not_found", 200), ("csv_user", 409), ("busy", 409)],
    )
    def test_delete_my_check(self, deps, monkeypatch, lambda_context, outcome, status):
        seen = []
        monkeypatch.setattr(
            api.repository, "delete_check", lambda conn, uid: seen.append(uid) or outcome
        )
        assert call("DELETE /me", lambda_context)[0] == 401
        token = tokens.sign(USER, int(time.time()) + 60, KEY)
        assert call("DELETE /me", lambda_context, token=token)[0] == status
        assert seen == [USER]  # only the user the link was signed for

    def test_start_fresh_keeps_the_account(self, deps, monkeypatch, lambda_context):
        seen = []
        monkeypatch.setattr(
            api.repository,
            "clear_account_profiles",
            lambda conn, sub, uid=None: seen.append((sub, uid))
            or {"deleted_checks": 1, "unlinked": 1},
        )
        invoke(self.event("DELETE /account/profiles", self.CLAIMS), lambda_context)
        invoke(
            self.event(
                "DELETE /account/profiles/{user_id}", self.CLAIMS, path={"user_id": str(USER)}
            ),
            lambda_context,
        )
        assert seen == [("c0ffee-sub", None), ("c0ffee-sub", USER)]


class TestUploadRecords:
    JOB = uuid.UUID("5d1c6a3e-9b0f-4f61-8d2a-7c3b9e1f0a42")

    def test_each_merchant_lists_only_its_own_uploads(self, deps, monkeypatch, lambda_context):
        seen = []
        rows = [{"job_id": self.JOB, "original_filename": "users.csv", "users_now": 4}]
        monkeypatch.setattr(
            api.repository, "list_uploads", lambda conn, account: seen.append(account) or rows
        )
        assert invoke({"routeKey": "GET /uploads"}, lambda_context)["statusCode"] == 401
        res = invoke({"routeKey": "GET /uploads", "requestContext": signed_in_as(MERCHANT)})
        assert json.loads(res["body"]) == [{**rows[0], "job_id": str(self.JOB)}]
        invoke({"routeKey": "GET /uploads", "requestContext": signed_in_as(ADMIN)})
        assert seen == ["merchant-sub", None]  # an admin sees every account's uploads

    def test_upload_progress_is_private_to_its_owner(self, deps, monkeypatch, lambda_context):
        monkeypatch.setattr(api.repository, "upload_owner", lambda conn, j: (True, "merchant-sub"))
        monkeypatch.setattr(
            api.repository,
            "get_job_progress",
            lambda conn, j: {
                "job": {
                    "status": "COMPLETED",
                    "attempts": 1,
                    "created_at": None,
                    "db_now": None,
                },
                "rejects": [],
            },
        )
        event = {"routeKey": "GET /uploads/{job_id}", "pathParameters": {"job_id": str(self.JOB)}}
        other = {**MERCHANT, "sub": "someone-else"}
        assert invoke({**event, "requestContext": signed_in_as(other)})["statusCode"] == 404
        assert invoke({**event, "requestContext": signed_in_as(MERCHANT)})["statusCode"] == 200


def test_one_account_per_verified_email_whatever_the_sign_in_method(
    deps, monkeypatch, lambda_context
):
    """A Google sign-in (its own Cognito sub) lands on the account of the same email."""
    rows = {"merchant@example.org": "password-sub"}  # created by an email+password sign-up
    monkeypatch.setattr(
        api.repository,
        "upsert_account",
        lambda conn, sub, email, admin=False: {
            "account_id": rows.setdefault(email, sub),
            "email": email,
        },
    )
    seen = []
    monkeypatch.setattr(
        api.repository, "list_uploads", lambda conn, account: seen.append(account) or []
    )
    google = {**MERCHANT, "sub": "google-sub", "identities": "[google]"}
    invoke({"routeKey": "GET /uploads", "requestContext": signed_in_as(google)}, lambda_context)
    assert seen == ["password-sub"]


def test_auth_config_offers_google_only_when_enabled(deps, monkeypatch, lambda_context):
    for enabled, domain in ((False, ""), (True, "d.auth.example")):
        monkeypatch.setattr(
            api,
            "dependencies",
            lambda enabled=enabled: api.Dependencies(
                db_host="h",
                db_secret_arn="a",
                bucket="b",
                s3=None,
                auth_domain="d.auth.example",
                google_sign_in=enabled,
            ),
        )
        body = json.loads(invoke({"routeKey": "GET /auth/config"}, lambda_context)["body"])
        assert (body["google"], body["domain"]) == (enabled, domain)


def test_admin_belongs_to_the_account_not_one_sign_in_method(deps, monkeypatch, lambda_context):
    """Admin recorded from the password login carries to a Google login of the same email."""
    accounts = {}  # email -> row

    def upsert(conn, sub, email, admin=False):
        row = accounts.setdefault(email, {"account_id": sub, "email": email, "is_admin": False})
        row["is_admin"] = row["is_admin"] or admin
        return row

    monkeypatch.setattr(api.repository, "upsert_account", upsert)
    monkeypatch.setattr(
        api.repository,
        "purge_csv_uploads",
        lambda conn, account=None: {"deleted_users": 0, "uploads": 0},
    )
    monkeypatch.setattr(api.repository, "list_uploads", lambda conn, account: [])
    google = {**MERCHANT, "sub": "google-sub"}  # not in the Cognito admin group
    every = {"routeKey": "DELETE /uploads", "queryStringParameters": {"scope": "all"}}
    assert invoke({**every, "requestContext": signed_in_as(google)})["statusCode"] == 403
    invoke(
        {
            "routeKey": "GET /uploads",
            "requestContext": signed_in_as({**ADMIN, "email": MERCHANT["email"]}),
        }
    )
    assert invoke({**every, "requestContext": signed_in_as(google)})["statusCode"] == 200
