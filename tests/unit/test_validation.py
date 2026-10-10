"""Unit tests for loan_engine.common.validation (PLAN.md §9, §17)."""

import io

import pytest

from loan_engine.common.validation import (
    DEFAULT_RULES,
    EmploymentType,
    MissingColumnsError,
    RowError,
    parse_email,
    parse_employment,
    parse_int_in_range,
    parse_user_id,
    rules_from_json,
    validate_csv,
)

HEADER = "user_id,name,email,monthly_income,credit_score,employment_status,age"
U1 = "b35de23e-755f-4c6a-81d8-f7dd99ce53ef"
U2 = "77fce4da-b901-4b27-b1bb-01989567b98b"


def lines(text: str) -> io.StringIO:
    """Feed text the way the ingest Lambda will: a text stream with newline=''."""
    return io.StringIO(text, newline="")


# ---------------------------------------------------------------- field parsers


class TestParseUserId:
    def test_canonicalizes_uppercase(self):
        assert parse_user_id(U1.upper()) == U1

    @pytest.mark.parametrize("bad", ["", "abc", "12345", U1[:-1]])
    def test_rejects_non_uuid(self, bad):
        with pytest.raises(RowError, match="invalid_user_id"):
            parse_user_id(bad)


class TestParseEmail:
    def test_trims_and_lowercases(self):
        assert parse_email("  Tara.Khan@Example.COM ") == "tara.khan@example.com"

    def test_missing(self):
        with pytest.raises(RowError, match="missing_email"):
            parse_email("   ")

    @pytest.mark.parametrize("bad", ["no-at-sign", "a@b", "a b@c.com", "a@@b.com"])
    def test_malformed(self, bad):
        with pytest.raises(RowError, match="invalid_email"):
            parse_email(bad)


class TestParseIntInRange:
    def test_valid_with_spaces(self):
        assert parse_int_in_range(" 725 ", "credit_score", 300, 900) == 725

    @pytest.mark.parametrize("bad", ["", "7.5", "-5", "+5", "1_000", "12k", "1,000"])
    def test_rejects_non_plain_digits(self, bad):
        # int() would silently accept "+5" and "1_000"; we must not.
        with pytest.raises(RowError, match="invalid_age"):
            parse_int_in_range(bad, "age", 18, 100)

    @pytest.mark.parametrize("value", ["17", "101"])
    def test_out_of_range(self, value):
        with pytest.raises(RowError, match="age_out_of_range"):
            parse_int_in_range(value, "age", 18, 100)

    def test_bounds_are_inclusive(self):
        assert parse_int_in_range("18", "age", 18, 100) == 18
        assert parse_int_in_range("100", "age", 18, 100) == 100


class TestParseEmployment:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Salaried", EmploymentType.SALARIED),
            ("Self-Employed", EmploymentType.SELF_EMPLOYED),
            (" self employed ", EmploymentType.SELF_EMPLOYED),
            ("SELF_EMPLOYED", EmploymentType.SELF_EMPLOYED),
            ("Business", EmploymentType.BUSINESS),
            ("business owner", EmploymentType.BUSINESS),
        ],
    )
    def test_aliases(self, raw, expected):
        assert parse_employment(raw) is expected

    def test_unknown_label(self):
        with pytest.raises(RowError, match="invalid_employment_status"):
            parse_employment("Student")


# ---------------------------------------------------------------- whole file


def test_happy_path_normalizes_row():
    csv_text = f"{HEADER}\n{U1},Dhruv Iyengar,Dhruv@Example.com,131000,725,Self-Employed,37\n"
    result = validate_csv(lines(csv_text))
    assert result.total_rows == 1
    assert result.rejects == []
    user = result.valid[0]
    assert user.email == "dhruv@example.com"
    assert user.employment_status is EmploymentType.SELF_EMPLOYED
    assert (user.monthly_income, user.credit_score, user.age) == (131000, 725, 37)


def test_bom_and_crlf_are_handled():
    # The real users.csv uses CRLF; Excel exports often add a BOM.
    csv_text = f"﻿{HEADER}\r\n{U1},A,a@x.com,50000,700,Salaried,30\r\n"
    result = validate_csv(lines(csv_text))
    assert len(result.valid) == 1
    assert result.rejects == []


def test_header_is_matched_by_name_not_position():
    header = "age,employment_status,credit_score,monthly_income,email,name,user_id"
    csv_text = f"{header}\n30,Salaried,700,50000,a@x.com,A,{U1}\n"
    user = validate_csv(lines(csv_text)).valid[0]
    assert (user.age, user.monthly_income, user.user_id) == (30, 50000, U1)


def test_header_case_and_spaces_are_ignored():
    header = " User_ID , Name,EMAIL,monthly_income,credit_score,employment_status,age"
    csv_text = f"{header}\n{U1},A,a@x.com,50000,700,Salaried,30\n"
    assert len(validate_csv(lines(csv_text)).valid) == 1


def test_name_column_is_optional():
    header = "user_id,email,monthly_income,credit_score,employment_status,age"
    csv_text = f"{header}\n{U1},a@x.com,50000,700,Salaried,30\n"
    user = validate_csv(lines(csv_text)).valid[0]
    assert user.name is None


def test_missing_required_column_fails_the_file():
    header = "user_id,name,email,monthly_income,employment_status,age"  # no credit_score
    with pytest.raises(MissingColumnsError) as exc:
        validate_csv(lines(f"{header}\n"))
    assert exc.value.missing == ["credit_score"]


def test_empty_file_fails():
    with pytest.raises(MissingColumnsError):
        validate_csv(lines(""))


def test_duplicate_user_id_last_occurrence_wins():
    csv_text = (
        f"{HEADER}\n"
        f"{U1},Old,old@x.com,30000,700,Salaried,30\n"
        f"{U2},Other,o@x.com,40000,710,Business,40\n"
        f"{U1},New,new@x.com,90000,750,Salaried,31\n"
    )
    result = validate_csv(lines(csv_text))
    by_id = {u.user_id: u for u in result.valid}
    assert len(result.valid) == 2
    assert by_id[U1].email == "new@x.com"
    assert [(r.row_number, r.reason) for r in result.rejects] == [(2, "duplicate_in_file")]


def test_bad_rows_are_rejected_with_row_numbers_and_good_rows_kept():
    csv_text = (
        f"{HEADER}\n"
        f"{U1},A,a@x.com,50000,700,Salaried,30\n"  # line 2 ok
        f"not-a-uuid,B,b@x.com,50000,700,Salaried,30\n"  # line 3
        f"{U2},C,c@x.com,50000,950,Salaried,30\n"  # line 4 score > 900
        f"{U2},D,d@x.com,50000,700,Student,30\n"  # line 5 bad employment
        f"{U2},E,e@x.com,50000,700\n"  # line 6 too few fields
        f"{U2},F,f@x.com,50000,700,Salaried,30,extra\n"  # line 7 too many fields
    )
    result = validate_csv(lines(csv_text))
    assert result.total_rows == 6
    assert len(result.valid) == 1
    assert [(r.row_number, r.reason) for r in result.rejects] == [
        (3, "invalid_user_id"),
        (4, "credit_score_out_of_range"),
        (5, "invalid_employment_status"),
        (6, "wrong_field_count"),
        (7, "wrong_field_count"),
    ]
    assert result.rejects[0].raw_line.startswith("not-a-uuid,B,")
    assert result.rejects[-1].raw_line.endswith(",extra")


def test_blank_lines_are_skipped_not_rejected():
    csv_text = f"{HEADER}\n\n{U1},A,a@x.com,50000,700,Salaried,30\n\n"
    result = validate_csv(lines(csv_text))
    assert result.total_rows == 1
    assert result.rejects == []


def test_quoted_field_with_comma():
    csv_text = f'{HEADER}\n{U1},"Khan, Tara",a@x.com,50000,700,Salaried,30\n'
    assert validate_csv(lines(csv_text)).valid[0].name == "Khan, Tara"


# ---------------------------------------------------------------- pluggable rules


class TestRulesFromJson:
    def test_empty_means_defaults(self):
        assert rules_from_json(None) is DEFAULT_RULES
        assert rules_from_json("  ") is DEFAULT_RULES

    def test_tightened_age_rejects_younger_users(self):
        rules = rules_from_json('{"age_min": 21}')
        csv_text = f"{HEADER}\n{U1},A,a@x.com,50000,700,Salaried,20\n"
        result = validate_csv(lines(csv_text), rules)
        assert [r.reason for r in result.rejects] == ["age_out_of_range"]
        # The default rules still accept the same row.
        assert len(validate_csv(lines(csv_text)).valid) == 1

    def test_extra_alias_is_added_not_replacing_defaults(self):
        rules = rules_from_json('{"employment_aliases": {"Freelancer": "self_employed"}}')
        assert parse_employment("freelancer", rules.employment_aliases) is (
            EmploymentType.SELF_EMPLOYED
        )
        assert parse_employment("Salaried", rules.employment_aliases) is EmploymentType.SALARIED

    @pytest.mark.parametrize(
        ("bad_json", "message"),
        [
            ('{"agemin": 21}', "unknown validation rule"),
            ('{"age_min": "21"}', "must be an integer"),
            ('{"age_min": true}', "must be an integer"),
            ('{"age_min": 60, "age_max": 50}', "age range"),
            ('{"credit_score_max": 999}', "credit_score range"),  # beyond the DB CHECK
            ('{"employment_aliases": {"student": "student"}}', "student"),
        ],
    )
    def test_bad_config_fails_loudly(self, bad_json, message):
        with pytest.raises(ValueError, match=message):
            rules_from_json(bad_json)


def test_header_spelling_variants_match_by_name():
    from loan_engine.common.validation import normalize_header

    assert normalize_header(
        ["﻿User ID", " Monthly Income ", "credit-score", "Employment_Status"]
    ) == [
        "user_id",
        "monthly_income",
        "credit_score",
        "employment_status",
    ]


def test_db_tls_is_verified_when_configured():
    from loan_engine.common import db

    assert db.tls_options({}) == {"sslmode": "require"}  # local tests and CI
    full = db.tls_options({"DB_SSLMODE": "verify-full"})
    assert full == {"sslmode": "verify-full", "sslrootcert": str(db.RDS_CA_BUNDLE)}
    assert db.RDS_CA_BUNDLE.read_text().count("BEGIN CERTIFICATE") >= 1  # shipped in the package
    custom = db.tls_options({"DB_SSLMODE": "verify-ca", "DB_SSLROOTCERT": "/tmp/ca.pem"})
    assert custom["sslrootcert"] == "/tmp/ca.pem"
