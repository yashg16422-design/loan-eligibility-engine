"""Validation for uploaded user CSVs (PLAN.md §9).

Pure logic only: no S3, no database, no logging side effects. The ingest Lambda
streams text lines in and gets back clean rows plus per-row rejects, so every
rule here is unit-testable with in-memory strings.
"""

from __future__ import annotations

import csv
import json
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, replace
from enum import StrEnum

REQUIRED_COLUMNS: tuple[str, ...] = (
    "user_id",
    "email",
    "monthly_income",
    "credit_score",
    "employment_status",
    "age",
)

# Plain digits only: Python's int() would also accept "+5", " 5" and "1_000".
_DIGITS = re.compile(r"[0-9]+")
# A deliberately simple check: one @, no spaces, a dot in the domain.
# Real deliverability is irrelevant: we never email CSV addresses.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_EMAIL_MAX_LEN = 254

# One CSV record keyed by column name, shaped like csv.DictReader output:
# a short row has None values, surplus values are a list under the key None.
Record = Mapping[str | None, str | list[str] | None]


class EmploymentType(StrEnum):
    """Canonical employment values stored in the database."""

    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    BUSINESS = "business"


# Keys are lowercased and trimmed before lookup, so "Self-Employed " also matches.
_DEFAULT_EMPLOYMENT_ALIASES: dict[str, EmploymentType] = {
    "salaried": EmploymentType.SALARIED,
    "self-employed": EmploymentType.SELF_EMPLOYED,
    "self employed": EmploymentType.SELF_EMPLOYED,
    "self_employed": EmploymentType.SELF_EMPLOYED,
    "business": EmploymentType.BUSINESS,
    "business owner": EmploymentType.BUSINESS,
}

# Hard outer limits = the CHECK constraints in sql/001_schema.sql. Rules may be
# tightened freely but never loosened past these, or inserts would fail in Postgres.
_DB_LIMITS: dict[str, tuple[int, int]] = {
    "income": (1, 2_147_483_647),  # INT column
    "credit_score": (300, 900),  # CIBIL scale
    "age": (18, 100),
}


@dataclass(frozen=True, slots=True)
class ValidationRules:
    """The tunable business rules for user rows (a pluggable seam).

    Defaults are PLAN.md §9. They can be changed without touching code by setting the
    ingest Lambda's VALIDATION_RULES env var to JSON (see `rules_from_json`), e.g.
    {"age_min": 21, "employment_aliases": {"freelancer": "self_employed"}}.
    """

    income_min: int = 1
    income_max: int = 100_000_000  # sanity cap: a typo like 5000000000 is rejected
    credit_score_min: int = 300
    credit_score_max: int = 900
    age_min: int = 18
    age_max: int = 100
    employment_aliases: Mapping[str, EmploymentType] = field(
        default_factory=lambda: dict(_DEFAULT_EMPLOYMENT_ALIASES)
    )


DEFAULT_RULES = ValidationRules()


def rules_from_json(text: str | None) -> ValidationRules:
    """Build rules from optional JSON overrides; empty or None means the defaults.

    Extra employment aliases are ADDED to the defaults (mapping onto the three
    canonical values). Unknown keys, min > max, or limits outside the database CHECK
    constraints raise ValueError, so a bad config fails loudly at cold start instead
    of silently mis-validating.
    """
    if not text or not text.strip():
        return DEFAULT_RULES
    overrides = json.loads(text)
    known = {f.name for f in fields(ValidationRules)}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError(f"unknown validation rule(s): {sorted(unknown)}")

    aliases = dict(_DEFAULT_EMPLOYMENT_ALIASES)
    extra_aliases = overrides.pop("employment_aliases", {})
    for key, value in overrides.items():
        # bool is a subclass of int in Python, so exclude it explicitly.
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"validation rule {key!r} must be an integer, got {value!r}")
    for label, canonical in extra_aliases.items():
        aliases[label.strip().lower()] = EmploymentType(canonical)  # ValueError if unknown

    rules = replace(DEFAULT_RULES, employment_aliases=aliases, **overrides)
    for name, (db_low, db_high) in _DB_LIMITS.items():
        low, high = getattr(rules, f"{name}_min"), getattr(rules, f"{name}_max")
        if not db_low <= low <= high <= db_high:
            raise ValueError(f"{name} range [{low}, {high}] must lie within [{db_low}, {db_high}]")
    return rules


class MissingColumnsError(ValueError):
    """The header lacks required columns. The whole file is rejected (job FAILED)."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"missing required column(s): {', '.join(missing)}")


class RowError(ValueError):
    """A single row is invalid; `reason` is a short machine-readable code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class UserRow:
    """One validated, normalized user, ready to load into the `users` table."""

    user_id: str
    name: str | None
    email: str
    monthly_income: int
    credit_score: int
    employment_status: EmploymentType
    age: int


@dataclass(frozen=True, slots=True)
class Reject:
    """A row we refused, kept for the `upload_rejects` table and the UI."""

    row_number: int
    raw_line: str
    reason: str


@dataclass(slots=True)
class ValidationResult:
    """Outcome of validating a whole file."""

    valid: list[UserRow] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)
    total_rows: int = 0


# ---------------------------------------------------------------------------
# Field parsers: each takes the raw cell text and returns a clean value or raises.
# ---------------------------------------------------------------------------


def normalize_header(header: Iterable[str]) -> list[str]:
    """Match columns by name, not position or spelling: drop a stray BOM, trim, lowercase,
    and treat spaces and hyphens as underscores ("Monthly Income" -> "monthly_income")."""
    return [re.sub(r"[\s-]+", "_", col.replace("﻿", "").strip().lower()) for col in header]


def find_missing_columns(header: Iterable[str]) -> list[str]:
    """Return the required columns absent from an already-normalized header."""
    present = set(header)
    return [col for col in REQUIRED_COLUMNS if col not in present]


def parse_user_id(value: str) -> str:
    """Return the canonical lowercase hyphenated form of a UUID."""
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        raise RowError("invalid_user_id") from None


def parse_name(value: str | None) -> str | None:
    """Name is optional; an empty cell becomes None rather than ''."""
    cleaned = (value or "").strip()
    return cleaned or None


def parse_email(value: str) -> str:
    """Trim and lowercase; reject empty or obviously malformed addresses."""
    cleaned = value.strip().lower()
    if not cleaned:
        raise RowError("missing_email")
    if len(cleaned) > _EMAIL_MAX_LEN or not _EMAIL.fullmatch(cleaned):
        raise RowError("invalid_email")
    return cleaned


def parse_int_in_range(value: str, field_name: str, low: int, high: int) -> int:
    """Parse a plain non-negative integer and check it lies in [low, high]."""
    cleaned = value.strip()
    if not _DIGITS.fullmatch(cleaned):
        raise RowError(f"invalid_{field_name}")
    number = int(cleaned)
    if not low <= number <= high:
        raise RowError(f"{field_name}_out_of_range")
    return number


def parse_employment(
    value: str, aliases: Mapping[str, EmploymentType] = _DEFAULT_EMPLOYMENT_ALIASES
) -> EmploymentType:
    """Map the free-text label onto one of the three canonical values."""
    try:
        return aliases[value.strip().lower()]
    except KeyError:
        raise RowError("invalid_employment_status") from None


def validate_row(row: Record, rules: ValidationRules = DEFAULT_RULES) -> UserRow:
    """Validate one CSV record (as produced by csv.DictReader) into a UserRow.

    Raises:
        RowError: with the reason of the first failing rule.
    """
    # DictReader stores surplus values under the key None and fills short rows with None.
    if None in row or any(row.get(col) is None for col in REQUIRED_COLUMNS):
        raise RowError("wrong_field_count")

    def cell(col: str) -> str:
        value = row.get(col)
        return value if isinstance(value, str) else ""

    return UserRow(
        user_id=parse_user_id(cell("user_id")),
        name=parse_name(cell("name")),
        email=parse_email(cell("email")),
        monthly_income=parse_int_in_range(
            cell("monthly_income"), "monthly_income", rules.income_min, rules.income_max
        ),
        credit_score=parse_int_in_range(
            cell("credit_score"), "credit_score", rules.credit_score_min, rules.credit_score_max
        ),
        employment_status=parse_employment(cell("employment_status"), rules.employment_aliases),
        age=parse_int_in_range(cell("age"), "age", rules.age_min, rules.age_max),
    )


# ---------------------------------------------------------------------------
# File-level validation
# ---------------------------------------------------------------------------


def _raw_line(row: Record) -> str:
    """Rebuild a readable version of the original line for the rejects table."""
    parts: list[str] = []
    for key, value in row.items():
        if key is None and isinstance(value, list):  # surplus fields
            parts.extend(str(v) for v in value)
        elif value is not None:
            parts.append(str(value))
    return ",".join(parts)


def validate_csv(lines: Iterable[str], rules: ValidationRules = DEFAULT_RULES) -> ValidationResult:
    """Validate a whole CSV given as an iterable of text lines.

    Taking lines (not a file path or S3 object) keeps this function pure: the
    caller decides where the bytes come from, and the same code runs on an S3
    stream in Lambda and on an in-memory list in tests.

    Rules: header matched by name; a duplicate `user_id` keeps the LAST
    occurrence and rejects earlier ones as `duplicate_in_file`.

    Raises:
        MissingColumnsError: if the file is empty or lacks a required column.
    """
    reader = csv.reader(lines)
    try:
        header = normalize_header(next(reader))
    except StopIteration:
        raise MissingColumnsError(list(REQUIRED_COLUMNS)) from None

    missing = find_missing_columns(header)
    if missing:
        raise MissingColumnsError(missing)

    result = ValidationResult()
    # user_id -> (row_number, raw_line, row). Insertion order keeps output stable.
    latest: dict[str, tuple[int, str, UserRow]] = {}

    for values in reader:
        if not any(v.strip() for v in values):
            continue  # blank lines (e.g. trailing newline) are not rows
        row_number = reader.line_num
        result.total_rows += 1
        record = _to_record(header, values)
        raw = _raw_line(record)
        try:
            user = validate_row(record, rules)
        except RowError as err:
            result.rejects.append(Reject(row_number, raw, err.reason))
            continue

        previous = latest.get(user.user_id)
        if previous is not None:
            prev_number, prev_raw, _ = previous
            result.rejects.append(Reject(prev_number, prev_raw, "duplicate_in_file"))
            # Delete first so the survivor moves to its newest position in the order.
            del latest[user.user_id]
        latest[user.user_id] = (row_number, raw, user)

    result.valid = [user for _, _, user in latest.values()]
    result.rejects.sort(key=lambda r: r.row_number)
    return result


def _to_record(header: list[str], values: list[str]) -> Record:
    """Zip a row with the header the same way csv.DictReader does.

    Missing trailing values become None and surplus values go under the key None,
    which lets `validate_row` detect a wrong field count explicitly.
    """
    record: dict[str | None, str | list[str] | None] = {}
    for i, col in enumerate(header):
        record[col] = values[i] if i < len(values) else None
    if len(values) > len(header):
        record[None] = values[len(header) :]
    return record
