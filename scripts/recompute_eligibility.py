#!/usr/bin/env python3
"""Recompute eligible users per lender straight from the CSV, WITHOUT the engine.

An independent check of the analytics chart ("Top lenders"): plain Python over the users CSV,
the products and the compiled rules. No database, no SQL, no classes, nothing shared with
the matching pipeline except the published criteria themselves. If this and the engine
agree, the chart is right.

    # Products and compiled rules exported read-only from RDS (scripts/psql.sh):
    #   \\copy (SELECT json_agg(p) FROM loan_products p WHERE is_active) TO 'products.json'
    #   \\copy (SELECT json_agg(r) FROM criteria_rules r
    #          WHERE prompt_version = 'compile_v1') TO 'rules.json'
    .venv/bin/python scripts/recompute_eligibility.py data/users.csv products.json \\
        --rules rules.json

Output: one JSON line per lender, {"lender", "users", "eligible_users"}, sorted like the chart
(eligible users, then users, then name). `users` = users with at least one offer from the lender
(eligible or "may qualify"); `eligible_users` = users eligible outright for at least one.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EMPLOYMENT = {
    "salaried": "salaried",
    "self-employed": "self_employed",
    "self employed": "self_employed",
    "self_employed": "self_employed",
    "business": "business",
    "business owner": "business",
}


# A plain "something@something.tld" check: the same bar the ingest Lambda applies.
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class User:
    user_id: str
    income: int
    score: int
    age: int
    employment: str


def read_users(text: str) -> list[User]:
    """Parse the CSV; rows that do not parse are skipped, and a repeated user_id keeps the last."""
    users: dict[str, User] = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            if not EMAIL.fullmatch(row["email"].strip().lower()):
                continue
            user = User(
                str(uuid.UUID(row["user_id"].strip())),
                int(row["monthly_income"]),
                int(row["credit_score"]),
                int(row["age"]),
                EMPLOYMENT[row["employment_status"].strip().lower()],
            )
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        in_range = 300 <= user.score <= 900 and 18 <= user.age <= 100
        if not (in_range and 1 <= user.income <= 100_000_000):
            continue
        users.pop(user.user_id, None)  # last occurrence wins, keeping file order
        users[user.user_id] = user
    return list(users.values())


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def passes_hard(user: User, p: dict[str, Any]) -> bool:
    def at_least(value: int, floor: float | str | None) -> bool:
        return floor is None or value >= float(floor)

    def at_most(value: int, ceiling: float | str | None) -> bool:
        return ceiling is None or value <= float(ceiling)

    kinds = p.get("employment_types")
    return (
        at_least(user.income, p.get("min_monthly_income"))
        and at_least(user.score, p.get("min_credit_score"))
        and at_most(user.score, p.get("max_credit_score"))
        and at_least(user.age, p.get("min_age"))
        and at_most(user.age, p.get("max_age"))
        and (kinds is None or user.employment in kinds)
    )


def rule_holds(user: User, rule: dict[str, Any]) -> bool:
    value = {"monthly_income": user.income, "credit_score": user.score, "age": user.age}.get(
        rule.get("field", "")
    )
    if value is None or rule.get("op") not in (">=", "<="):
        return True  # nothing checkable: the rule cannot reject anyone
    limit = float(rule["value"])
    return value >= limit if rule["op"] == ">=" else value <= limit


def tier(user: User, p: dict[str, Any], compiled: dict[str, dict[str, Any]]) -> str | None:
    """'eligible', 'conditional' (may qualify) or None (not a match) for one user and product."""
    if not passes_hard(user, p):
        return None
    text = p.get("other_criteria_text")
    if not text:
        return "eligible"
    entry = compiled.get(text_hash(text))
    if entry is None:
        return "conditional"  # criteria not compiled: shown as "may qualify"
    applicable = [
        r for r in entry.get("rules") or [] if r.get("applies_to") in ("any", user.employment)
    ]
    if not all(rule_holds(user, r) for r in applicable):
        return None
    return "conditional" if entry.get("requirements") else "eligible"


def recompute(
    users: Iterable[User], products: list[dict[str, Any]], rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Per lender: users with any offer, and users eligible outright for at least one product."""
    compiled = {r.get("criteria_text_hash") or text_hash(r["criteria_text"]): r for r in rules}
    active = [p for p in products if p.get("is_active", True)]
    any_offer: dict[str, set[str]] = defaultdict(set)
    eligible: dict[str, set[str]] = defaultdict(set)
    for user in users:
        for p in active:
            t = tier(user, p, compiled)
            if t is not None:
                any_offer[p["lender"]].add(user.user_id)
                if t == "eligible":
                    eligible[p["lender"]].add(user.user_id)
    rows = [
        {"lender": lender, "users": len(ids), "eligible_users": len(eligible[lender])}
        for lender, ids in any_offer.items()
    ]
    return sorted(rows, key=lambda r: (-r["eligible_users"], -r["users"], r["lender"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("users_csv", type=Path)
    parser.add_argument("products_json", type=Path)
    parser.add_argument("--rules", type=Path, help="compiled criteria_rules export (JSON list)")
    args = parser.parse_args()
    users = read_users(args.users_csv.read_text(encoding="utf-8-sig"))
    products = json.loads(args.products_json.read_text())
    rules = json.loads(args.rules.read_text()) if args.rules else []
    for row in recompute(users, products, rules or []):
        print(json.dumps(row))


if __name__ == "__main__":
    main()
