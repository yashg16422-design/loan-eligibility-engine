"""Serve the built dashboard (dashboard/ -> loan_engine/api/static/) from the api Lambda.

Same origin as the JSON API: no CORS, no extra hosting resources. Vite fingerprints every
asset file name, so assets are cached for a year and index.html is never cached.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

STATIC_DIR = Path(__file__).with_name("static")
INDEX = "index.html"
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}
TEXT_PREFIXES = ("text/", "application/json", "image/svg+xml")


@dataclass(frozen=True, slots=True)
class StaticFile:
    path: Path
    content_type: str
    immutable: bool


def resolve(request_path: str, root: Path = STATIC_DIR) -> StaticFile | None:
    """Map a URL path under /app to a file, or None.

    Traversal-safe: '..', absolute and hidden segments are refused before touching the
    disk, and the resolved path must stay inside `root`. A path without an extension is a
    client-side route, so it gets index.html (single-page app fallback).
    """
    parts = PurePosixPath(request_path.lstrip("/")).parts
    if any(p in ("..", ".") or p.startswith(".") for p in parts):
        return None
    rel = PurePosixPath(*parts) if parts else PurePosixPath(INDEX)
    if not rel.suffix:
        rel = PurePosixPath(INDEX)
    content_type = TYPES.get(rel.suffix.lower())
    if content_type is None:
        return None
    candidate = (root / rel).resolve()
    if not candidate.is_file() or not candidate.is_relative_to(root.resolve()):
        return None
    return StaticFile(candidate, content_type, immutable=rel.parts[:1] == ("assets",))


def response(file: StaticFile) -> dict:
    """API Gateway (HTTP API v2) response for a static file."""
    data = file.path.read_bytes()
    is_text = file.content_type.startswith(TEXT_PREFIXES)
    return {
        "statusCode": 200,
        "headers": {
            "content-type": file.content_type,
            "cache-control": "public, max-age=31536000, immutable"
            if file.immutable
            else "no-cache",
            "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer",
            **({"x-frame-options": "DENY"} if file.path.name == INDEX else {}),
        },
        "body": data.decode("utf-8") if is_text else base64.b64encode(data).decode(),
        "isBase64Encoded": not is_text,
    }
