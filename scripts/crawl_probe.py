"""Evaluate candidate lender pages for Workflow A (PLAN.md §10 "source selection").

Run it FROM THE CRAWLER'S NETWORK (the n8n EC2), because sites may treat cloud IPs
differently from a home connection. Polite by design: robots.txt is checked first and
a disallowed page is never fetched; one request per page; standard library only
(runs on the stock Python of Amazon Linux).

Usage:  python3 crawl_probe.py [urls-file]     (default: the built-in candidate list)
Output: one line per candidate + a JSON summary on the last line.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlsplit

# A real, identifiable user agent: we don't pretend to be something we're not.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 LoanEligibilityEngine-assignment/1.0"
)
TIMEOUT_S = 20

CANDIDATES = [
    "https://www.bankbazaar.com/personal-loan-interest-rate.html",
    "https://www.paisabazaar.com/personal-loan/interest-rates/",
    "https://www.bajajfinserv.in/personal-loan-eligibility-criteria",
    "https://www.tatacapital.com/personal-loan/eligibility.html",
    "https://www.hdfcbank.com/personal/borrow/popular-loans/personal-loan/eligibility",
    "https://www.icicibank.com/personal-banking/loans/personal-loan/eligibility",
    "https://www.axisbank.com/retail/loans/personal-loan/eligibility",
    "https://www.kotak.com/en/personal-banking/loans/personal-loan/eligibility.html",
    "https://sbi.co.in/web/personal-banking/loans/personal-loans/xpress-credit",
    "https://www.idfcfirstbank.com/personal-banking/loans/personal-loan/eligibility",
]

# Signals that eligibility data is in the server-rendered HTML (not injected by JS).
SIGNALS = {
    "rate%": re.compile(r"\d{1,2}(?:\.\d{1,2})?\s*%"),
    "income": re.compile(r"(?i)(?:monthly|net)\s+(?:income|salary)|income of|salary of"),
    "cibil": re.compile(r"(?i)cibil|credit score"),
    "age": re.compile(r"(?i)\b(?:2[0-9]|1[89])\s*(?:years|yrs)\b|age"),
    "rupee": re.compile(r"₹|Rs\.?\s?\d|INR"),
}


def robots_allows(url: str) -> bool | None:
    """True/False from the site's robots.txt; None if robots.txt itself was unreachable."""
    parts = urlsplit(url)
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        parser.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return parser.can_fetch(USER_AGENT, url)


def visible_text(html: str) -> str:
    """Strip scripts/styles/tags: roughly what a no-JS crawler can actually read."""
    html = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()


def probe(url: str) -> dict:
    result: dict = {"url": url}
    allowed = robots_allows(url)
    result["robots"] = {True: "allowed", False: "DISALLOWED", None: "unreachable"}[allowed]
    if allowed is False:
        return result  # respect robots.txt: never fetch
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            html = response.read().decode("utf-8", errors="replace")
            result["status"] = response.status
    except urllib.error.HTTPError as err:
        result["status"] = err.code
        return result
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        result["status"] = f"error: {getattr(err, 'reason', err)}"
        return result
    result["seconds"] = round(time.monotonic() - started, 1)
    text = visible_text(html)
    result["html_kb"] = len(html) // 1024
    result["text_kb"] = len(text) // 1024
    result["signals"] = {name: len(rx.findall(text)) for name, rx in SIGNALS.items()}
    # A page whose readable text is tiny, or that lacks rates/income, is probably JS-rendered.
    result["server_rendered"] = result["text_kb"] >= 3 and all(
        result["signals"][k] > 0 for k in ("rate%", "income")
    )
    return result


def main() -> None:
    urls = CANDIDATES
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    results = []
    for url in urls:
        r = probe(url)
        results.append(r)
        print(
            f"{r.get('status', '-')!s:>8} robots={r['robots']:<11} "
            f"text={r.get('text_kb', '-')!s:>4}KB ssr={r.get('server_rendered', '-')!s:<5} "
            f"{r.get('signals', '')} {url}",
            flush=True,
        )
        time.sleep(1)  # be gentle even across different hosts
    print(json.dumps(results))


if __name__ == "__main__":
    main()
