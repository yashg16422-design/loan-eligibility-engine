"""Serve the built front ends from the api Lambda: the app (dashboard/ -> static/, at /app)
and the landing page (web/ -> site/, at /).

Same origin as the JSON API: no CORS, no extra hosting resources. Vite fingerprints every
asset file name, so assets are cached for a year and index.html is never cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from starlette.responses import Response

STATIC_DIR = Path(__file__).with_name("static")  # the app, a single-page app under /app
SITE_DIR = Path(__file__).with_name("site")  # the landing page and its assets under /
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
    ".woff": "font/woff",
    ".txt": "text/plain; charset=utf-8",
}


@dataclass(frozen=True, slots=True)
class StaticFile:
    path: Path
    content_type: str
    immutable: bool


def resolve(request_path: str, root: Path = STATIC_DIR, spa: bool = True) -> StaticFile | None:
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
        if not spa and parts:
            return None  # the landing is one page: unknown paths are 404s, not index.html
        rel = PurePosixPath(INDEX)
    content_type = TYPES.get(rel.suffix.lower())
    if content_type is None:
        return None
    candidate = (root / rel).resolve()
    if not candidate.is_file() or not candidate.is_relative_to(root.resolve()):
        return None
    return StaticFile(candidate, content_type, immutable=rel.parts[:1] == ("assets",))


def response(file: StaticFile) -> Response:
    """The HTTP response for a static file (Mangum base64-encodes binary types for Lambda)."""
    return Response(
        file.path.read_bytes(),
        media_type=file.content_type,
        headers={
            "cache-control": "public, max-age=31536000, immutable"
            if file.immutable
            else "no-cache",
            "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer",
            **({"x-frame-options": "DENY"} if file.path.name == INDEX else {}),
        },
    )
