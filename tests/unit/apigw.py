"""Test helper: send a short test event through the real Lambda entry point.

Tests describe a request the way API Gateway names it ({"routeKey": "GET /uploads/{job_id}",
"pathParameters": {...}, "body": ..., "headers": ..., "requestContext": {"authorizer": ...}}).
`invoke` expands that into the full HTTP API v2 event API Gateway sends, so every test runs
Mangum + FastAPI routing + our handler exactly as production does.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from loan_engine.api import handler as api
from tests.conftest import FakeLambdaContext


def v2_event(event: dict[str, Any]) -> dict[str, Any]:
    method, route = event["routeKey"].split(" ", 1)
    params = event.get("pathParameters") or {}
    path = route
    for name, value in params.items():
        path = path.replace(f"{{{name}+}}", value).replace(f"{{{name}}}", value)
    query = event.get("queryStringParameters") or {}
    context = {
        "accountId": "000000000000",
        "apiId": "test",
        "domainName": "test.execute-api.ap-southeast-2.amazonaws.com",
        "domainPrefix": "test",
        "http": {
            "method": method,
            "path": path,
            "protocol": "HTTP/1.1",
            "sourceIp": "203.0.113.7",
            "userAgent": "pytest",
        },
        "requestId": "req-1",
        "routeKey": event["routeKey"],
        "stage": "$default",
        "time": "10/Oct/2026:00:00:00 +0000",
        "timeEpoch": 0,
        **(event.get("requestContext") or {}),
    }
    full: dict[str, Any] = {
        "version": "2.0",
        "routeKey": event["routeKey"],
        "rawPath": path,
        "rawQueryString": urlencode(query),
        "headers": {"host": context["domainName"], **(event.get("headers") or {})},
        "requestContext": context,
        "isBase64Encoded": bool(event.get("isBase64Encoded")),
    }
    if event.get("body") is not None:
        full["body"] = event["body"]
    if params:
        full["pathParameters"] = params
    if query:
        full["queryStringParameters"] = query
    return full


def invoke(event: dict[str, Any], context: object | None = None) -> dict[str, Any]:
    """The Lambda response for a short test event (status, headers, body as API Gateway sees)."""
    return api.handler(v2_event(event), context or FakeLambdaContext())
