"""Unit tests for the migrate Lambda's pure logic and the secrets parser."""

import json

import pytest

from loan_engine.common.secrets import DbCredentials, parse_db_secret
from loan_engine.migrate.handler import SQL_DIR, numbered_migrations, pending_migrations


class TestNumberedMigrations:
    def test_sorted_by_version_and_ignores_other_files(self):
        files = ["010_late.sql", "R__grants.sql", "002_b.sql", "notes.md", "001_a.sql"]
        assert numbered_migrations(files) == ["001_a.sql", "002_b.sql", "010_late.sql"]

    def test_ignores_badly_named_files(self):
        # Two digits, uppercase, or no description are not migrations.
        assert numbered_migrations(["01_a.sql", "001_A.sql", "001.sql", "brute_force.sql"]) == []

    def test_duplicate_version_is_an_error(self):
        with pytest.raises(ValueError, match="duplicate migration version 002"):
            numbered_migrations(["002_a.sql", "002_b.sql"])


class TestPendingMigrations:
    def test_skips_already_applied(self):
        available = ["001_schema.sql", "002_more.sql", "R__grants.sql"]
        assert pending_migrations(available, {"001_schema.sql"}) == ["002_more.sql"]

    def test_nothing_pending_on_rerun(self):
        assert pending_migrations(["001_schema.sql"], {"001_schema.sql"}) == []


def test_repo_sql_dir_has_the_schema_and_grants():
    """The paths the Lambda will use really exist in the package layout."""
    names = sorted(p.name for p in SQL_DIR.glob("*.sql"))
    assert "001_schema.sql" in numbered_migrations(names)
    assert "R__grants.sql" in names


class TestParseDbSecret:
    def test_rds_managed_format(self):
        creds = parse_db_secret(json.dumps({"username": "dbadmin", "password": "s3cret"}))
        assert creds == DbCredentials("dbadmin", "s3cret")

    @pytest.mark.parametrize("payload", [{}, {"username": "x"}, {"username": "", "password": "p"}])
    def test_missing_fields(self, payload):
        with pytest.raises(ValueError, match="username"):
            parse_db_secret(json.dumps(payload))

    def test_repr_never_leaks_the_password(self):
        assert "s3cret" not in repr(DbCredentials("dbadmin", "s3cret"))
