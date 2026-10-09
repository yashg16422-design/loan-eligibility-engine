"""Validation of the borrower's saved preferences (pure; the SQL CHECKs are the backstop)."""

from __future__ import annotations

import uuid
from typing import Any

LIMITS = {"shortlist": 50, "top3": 3, "hidden": 200}


class PreferencesError(ValueError):
    """Invalid preferences body; the message is safe to show the client."""


def _uuid_list(value: object, name: str) -> list[uuid.UUID]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > LIMITS[name]:
        raise PreferencesError(f"{name} must be a list of at most {LIMITS[name]} product ids")
    try:
        ids = [uuid.UUID(str(v)) for v in value]
    except ValueError:
        raise PreferencesError(f"{name} contains an invalid product id") from None
    return list(dict.fromkeys(ids))  # de-duplicate, keep the user's order


def parse_preferences(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize a PUT /me/preferences body.

    Rules: the top 3 must come from the shortlist (you compare what you saved), and a
    hidden product leaves the shortlist and the top 3.
    """
    hidden = _uuid_list(body.get("hidden"), "hidden")
    shortlist = [p for p in _uuid_list(body.get("shortlist"), "shortlist") if p not in hidden]
    top3 = [p for p in _uuid_list(body.get("top3"), "top3") if p in shortlist]
    alerts = body.get("alerts", False)
    if not isinstance(alerts, bool):
        raise PreferencesError("alerts must be true or false")
    return {"shortlist": shortlist, "top3": top3, "hidden": hidden, "alerts": alerts}
