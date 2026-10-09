"""Headless-browser renderer: the `fetch: rendered` half of the crawler.

Some lender pages draw their rates and eligibility with JavaScript, so a plain HTTP
fetch sees an empty shell. n8n calls this service for those pages only:

    POST /render  {"url": "https://...", "timeout_ms": 25000}
      -> 200 {"url", "final_url", "status", "challenge", "title", "text", "html", "ms"}
      -> 400 {"error"} for unsafe/invalid URLs
    GET  /healthz -> {"status": "ok"}

Design: one Chromium process for the container's lifetime, a fresh incognito context
per request (no cookies or state carried between sites), images/fonts/media blocked
for speed, and requests served one at a time to fit a 2 GB instance. It is never
published on a host port: only n8n reaches it on the internal Docker network.
Polite by policy: robots.txt is checked by n8n before calling this; bot challenges
are reported (challenge=true) and never bypassed.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from playwright.sync_api import Browser, Error, Route, sync_playwright
from url_safety import UnsafeUrlError, check_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("renderer")

PORT = int(os.environ.get("PORT", "3000"))
USER_AGENT = os.environ.get(
    "RENDER_USER_AGENT",
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 LoanEligibilityEngine-assignment/1.0",
)
MAX_HTML_BYTES = 3_000_000
BLOCKED_RESOURCES = {"image", "media", "font"}
SCROLL_STEPS = 6
SETTLE_MS = 1500
# Phrases of common bot-protection interstitials. Seeing one means: stop, report.
# All text in the body, hidden accordions included, minus script/style/noscript noise.
TEXT_JS = """() => {
  const body = document.body.cloneNode(true);
  body.querySelectorAll('script,style,noscript,template,svg').forEach(n => n.remove());
  body.querySelectorAll('br,p,div,li,tr,h1,h2,h3,h4,h5,h6,section,article,td,th')
      .forEach(n => n.append(document.createTextNode('\\n')));
  return body.textContent.replace(/[ \\t\\u00a0]+/g, ' ').replace(/\\n\\s*\\n+/g, '\\n').trim();
}"""
CHALLENGE = re.compile(
    r"(?i)captcha|verify you are human|are you a robot|access denied|attention required|"
    r"checking your browser|unusual traffic"
)


def render(browser: Browser, url: str, timeout_ms: int) -> dict[str, Any]:
    """Load the page in a fresh context and return its rendered content."""
    started = time.monotonic()
    context = browser.new_context(user_agent=USER_AGENT, java_script_enabled=True)
    try:
        page = context.new_page()

        def guard(route: Route) -> None:
            request = route.request
            if request.resource_type in BLOCKED_RESOURCES:
                route.abort()
                return
            # Re-check every navigation/redirect hop, not just the first URL (SSRF).
            if request.is_navigation_request():
                try:
                    check_url(request.url)
                except UnsafeUrlError:
                    route.abort()
                    return
            route.continue_()

        page.route("**/*", guard)
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        # Give client-side rendering a moment to fill in rates/eligibility.
        # Busy pages (analytics, chat widgets) never go idle; the content is usually there.
        with contextlib.suppress(Error):
            page.wait_for_load_state("networkidle", timeout=min(10_000, timeout_ms))
        # Many sites lazy-load sections as you scroll: scroll down in steps, then settle.
        for _ in range(SCROLL_STEPS):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(400)
        page.wait_for_timeout(SETTLE_MS)
        # Keep the richer of two views: textContent includes collapsed accordions/tabs
        # (hidden, so innerText skips them); innerText survives some frameworks whose
        # content textContent misses. The LLM later reads only the eligibility section.
        hidden_included = page.evaluate(TEXT_JS)
        visible = page.inner_text("body")
        text = hidden_included if len(hidden_included) >= len(visible) else visible
        html = page.content()[:MAX_HTML_BYTES]
        status = response.status if response else None
        return {
            "url": url,
            "final_url": page.url,
            "status": status,
            "challenge": bool(status in (403, 429) or CHALLENGE.search(text[:5000])),
            "title": page.title(),
            "text": text,
            "html": html,
            "ms": int((time.monotonic() - started) * 1000),
        }
    finally:
        context.close()


class Handler(BaseHTTPRequestHandler):
    browser: Browser  # set at startup

    def _send(self, code: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/render":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(length, 10_000)) or b"{}")
            url = check_url(str(body.get("url", "")))
            timeout_ms = max(5_000, min(int(body.get("timeout_ms", 25_000)), 60_000))
        except (ValueError, UnsafeUrlError) as err:
            self._send(400, {"error": str(err)})
            return
        try:
            result = render(self.browser, url, timeout_ms)
        except Error as err:
            log.warning("render failed for %s: %s", url, err)
            self._send(502, {"error": f"render failed: {str(err).splitlines()[0]}", "url": url})
            return
        log.info(
            "rendered %s status=%s ms=%s challenge=%s text=%dB",
            url,
            result["status"],
            result["ms"],
            result["challenge"],
            len(result["text"]),
        )
        self._send(200, result)

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence the default per-request access log; render() logs what matters."""


def main() -> None:
    with sync_playwright() as pw:
        Handler.browser = pw.chromium.launch(headless=True)
        # HTTPServer (not Threading): one render at a time keeps memory predictable.
        # 0.0.0.0 inside the container only: no host port is published (compose).
        server = HTTPServer(("0.0.0.0", PORT), Handler)
        log.info("renderer listening on :%d", PORT)
        server.serve_forever()


if __name__ == "__main__":
    main()
