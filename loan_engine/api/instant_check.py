"""Instant eligibility check: one visitor's four numbers -> a 1-row CSV for the real pipeline.

Why a CSV and not a direct insert: the visitor then travels the exact path a bulk upload
takes (S3 -> SQS -> ingest -> webhook -> Workflow B -> matches), so the demo proves the
whole system, and the validation rules are literally the same code (`validate_row`).

No real email is ever collected. The row carries a reserved, undeliverable address
(RFC 2606 `.invalid`), and Workflow C only ever mails the configured test aliases anyway.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
import uuid

from loan_engine.common.validation import (
    RowError,
    UserRow,
    ValidationRules,
    validate_row,
)

# The bulk-upload column order (name is optional there, but always present here).
CSV_HEADER = (
    "user_id",
    "name",
    "email",
    "monthly_income",
    "credit_score",
    "employment_status",
    "age",
)
MAX_CHECKS_PER_DAY = 100  # SES sandbox sends 200 emails/day; leave room for real uploads
MAX_CHECKS_PER_REQUESTER_PER_DAY = 20  # one visitor cannot use up everyone's daily budget
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# Friendly messages for the validator's reason codes (the API returns them as-is).
MESSAGES = {
    "invalid_monthly_income": "Monthly income must be a whole number of rupees.",
    "monthly_income_out_of_range": "Monthly income is outside the accepted range.",
    "invalid_credit_score": "Credit score must be a whole number.",
    "credit_score_out_of_range": "Credit score must be between 300 and 900.",
    "invalid_age": "Age must be a whole number.",
    "age_out_of_range": "Age must be between 18 and 100.",
    "invalid_employment_status": "Employment type must be salaried, self-employed or business.",
}


class CheckInputError(ValueError):
    """The visitor's input failed validation; the message is safe to show them."""


def placeholder_email(user_id: uuid.UUID) -> str:
    """A unique, undeliverable address: the users table requires one, nobody receives it."""
    return f"instant-check+{user_id.hex[:12]}@example.invalid"


def clean_name(value: object) -> str:
    """Optional display name: text only, no control characters, at most 60 characters."""
    if not isinstance(value, str):
        return ""
    return _CONTROL.sub("", value).strip()[:60]


def to_user_row(body: dict, user_id: uuid.UUID, rules: ValidationRules) -> UserRow:
    """Validate the request body with the same rules as a CSV row.

    Raises:
        CheckInputError: with a message the visitor can act on.
    """
    record = {
        "user_id": str(user_id),
        "name": clean_name(body.get("name")),
        "email": placeholder_email(user_id),
        # str(): the form may send numbers or strings; the CSV validator parses text.
        "monthly_income": str(body.get("monthly_income", "")),
        "credit_score": str(body.get("credit_score", "")),
        "employment_status": str(body.get("employment_status", "")).replace("_", "-"),
        "age": str(body.get("age", "")),
    }
    try:
        return validate_row(record, rules)
    except RowError as err:
        raise CheckInputError(MESSAGES.get(err.reason, "Please check the values.")) from None


def to_csv(row: UserRow) -> bytes:
    """The 1-row CSV the ingest Lambda will read (csv module = correct quoting of the name)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerow(
        [
            row.user_id,
            row.name or "",
            row.email,
            row.monthly_income,
            row.credit_score,
            row.employment_status.value,
            row.age,
        ]
    )
    return out.getvalue().encode("utf-8")


def requester_hash(source_ip: str | None, key: bytes) -> str | None:
    """A keyed hash of the caller's IP for the per-requester cap; the raw IP is never stored.

    Keyed (HMAC) rather than a plain hash: the IPv4 space is small enough to brute-force an
    unkeyed hash back to the address.
    """
    if not source_ip:
        return None
    return hmac.new(key, source_ip.strip().encode(), hashlib.sha256).hexdigest()[:32]
