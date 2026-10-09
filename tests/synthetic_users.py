"""The 10k-user CSV for the DB integration tests: the real file if present, else a synthetic twin.

`data/users.csv` is never committed (it contains personal-looking data), so CI would otherwise
skip the Treasure Hunt proofs. The synthetic file reproduces the MEASURED profile of the real
one (PLAN.md §9): 10,000 rows, lowercase UUIDs, `@example.com` emails, income 25,000-150,000
in steps of 1,000, credit score 650-800 in steps of 5, age 22-50, a roughly even split of the
three employment labels as written in the file, CRLF line endings. A fixed seed makes it
identical on every run, so a failure is reproducible.
"""

from __future__ import annotations

import random
import uuid
from pathlib import Path

REAL_CSV = Path(__file__).resolve().parents[1] / "data" / "users.csv"
ROWS = 10_000
SEED = 20261008  # the day the assignment arrived
FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Vihaan", "Anaya", "Arjun", "Sara"]
LAST = ["Shah", "Patel", "Iyer", "Nair", "Mehta", "Desai", "Rao", "Gupta", "Kapoor", "Singh"]
EMPLOYMENT = ["Salaried", "Self-Employed", "Business"]


def synthetic_users_csv(rows: int = ROWS, seed: int = SEED) -> bytes:
    """A deterministic CSV with the real file's columns, value ranges and line endings."""
    rng = random.Random(seed)
    lines = ["user_id,name,email,monthly_income,credit_score,employment_status,age"]
    for _ in range(rows):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        lines.append(
            ",".join(
                [
                    str(uuid.UUID(int=rng.getrandbits(128), version=4)),
                    f"{first} {last}",
                    f"{first}.{last}@example.com".lower(),
                    str(rng.randrange(25_000, 150_001, 1_000)),
                    str(rng.randrange(650, 801, 5)),
                    rng.choice(EMPLOYMENT),
                    str(rng.randint(22, 50)),
                ]
            )
        )
    return ("\r\n".join(lines) + "\r\n").encode()


def users_csv_bytes() -> bytes:
    """The real 10k file when it exists locally, otherwise its synthetic twin (CI)."""
    return REAL_CSV.read_bytes() if REAL_CSV.exists() else synthetic_users_csv()
