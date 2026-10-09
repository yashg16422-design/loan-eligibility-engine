"""Measure which lender pages Workflow A can legitimately use, and save them as fixtures.

Channels (PLAN.md §10.1):
  * bankbazaar  - hub page -> per-lender links  <lender>-personal-loan.html
  * paisabazaar - hub page -> per-lender links  /<lender>/personal-loan/
  * direct      - lender product pages found via each bank's sitemap.xml (seed list)

Rules (the same ones the n8n crawler follows):
  * robots.txt is checked for every URL; a disallowed page is never fetched.
  * Plain HTTP only. 403/429 or a challenge page = the site blocks bots -> skipped,
    never retried with a browser.
  * Text = visible HTML text + embedded structured data (ld+json, e.g. FAQPage),
    which is where many JS-heavy sites ship their content.
  * A page is usable only if its best "eligibility" window contains real criteria.

Standard library only (runs on the EC2's stock Python too).
Usage: python3 scripts/crawl_inventory.py [--save-dir DIR] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlsplit

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 LoanEligibilityEngine-assignment/1.0"
)
MIN_INTERVAL_S = 1.0  # per host

HUBS = {
    "bankbazaar": (
        "https://www.bankbazaar.com/personal-loan.html",
        re.compile(r"^https://www\.bankbazaar\.com/([a-z0-9-]+)-personal-loan\.html$"),
    ),
    "paisabazaar": (
        "https://www.paisabazaar.com/personal-loan/",
        re.compile(r"^https://www\.paisabazaar\.com/([a-z0-9-]+)/personal-loan/?$"),
    ),
}
# Slugs that match the URL shape but are articles/tools, not a lender's product page.
NOT_A_LENDER = re.compile(
    r"(^|-)(how|track|apply|instant|online|best|top|for|calculator|status|customer|care|"
    r"preclosure|interest|emi|eligibility|documents|pre-approved|bad|cibil|apps?|loan|category|reviews?|hindi|tamil|telugu|marathi|blog|news)(-|$)"
)
# Found via each bank's sitemap.xml (see scripts/crawl_probe.py history in the README).
DIRECT = {
    "icici": "https://www.icici.bank.in/personal-banking/loans/personal-loan",
    "idfc-first": "https://www.idfcfirst.bank.in/personal-banking/loans/personal-loan",
    "tata-capital": "https://www.tatacapital.com/personal-loan.html",
    "indusind": "https://www.indusind.bank.in/in/en/personal/loans/personal-loan.html",
    "sbi": "https://sbi.bank.in/web/personal-banking/loans/personal-loans/sbi-personal-loan",
    "federal": "https://www.federal.bank.in/personal-loans",
    "bajaj-finserv": "https://www.bajajfinserv.in/personal-loan-details",
    "axis": "https://www.axisbank.com/retail/loans/personal-loan/eligibility",
    "bank-of-baroda": "https://bankofbaroda.bank.in/loans/personal-loan/baroda-personal-loan",
}

CHALLENGE = re.compile(
    r"(?i)captcha|verify you are human|are you a robot|request forbidden|access denied|"
    r"attention required|checking your browser|unusual traffic"
)
SIGNALS = {
    "age": re.compile(r"(?i)\b(?:1[89]|[2-7]\d)\s*(?:years?|yrs)\b"),
    "money": re.compile(r"(?i)(?:₹|rs\.?|inr)\s?[\d,]{4,}|\d+(?:\.\d+)?\s*(?:lakh|lac)"),
    "income": re.compile(r"(?i)income|salary|earning"),
    "credit": re.compile(r"(?i)cibil|credit score"),
    "employment": re.compile(r"(?i)salaried|self[- ]employed|business"),
    "rate": re.compile(r"\d{1,2}(?:\.\d{1,2})?\s*%"),
}

_last_hit: dict[str, float] = defaultdict(float)
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def polite_get(url: str) -> tuple[int, str]:
    """GET with a per-host minimum interval. Returns (status, body)."""
    host = urlsplit(url).netloc
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_hit[host])
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        return 0, f"error: {getattr(err, 'reason', err)}"


def robots_allows(url: str) -> bool:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots:
        parser = urllib.robotparser.RobotFileParser(f"{origin}/robots.txt")
        try:
            parser.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            parser = None
        _robots[origin] = parser
    parser = _robots[origin]
    return True if parser is None else parser.can_fetch(USER_AGENT, url)


def embedded_text(html: str) -> str:
    """Text from ld+json blocks (FAQPage Q&A etc.): content JS sites ship in the HTML."""
    out: list[str] = []
    for block in re.findall(
        r'(?is)<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in ("name", "text", "description"):
                    if isinstance(node.get(key), str):
                        out.append(node[key])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return "\n".join(out)


def visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)<(br|/p|/div|/li|/tr|/h[1-6])\b[^>]*>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#8377;", "₹")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def best_eligibility_window(text: str, size: int = 2500) -> tuple[str, int]:
    """Pick the 'eligib…' window followed by the most distinct criteria signals.

    Scoring windows (instead of taking the first match) skips navigation menus
    like "Home Loan eligibility", which contain the word but no criteria.
    """
    best, best_score = "", 0
    for match in re.finditer(r"(?i)eligib", text):
        window = text[match.start() : match.start() + size]
        score = sum(1 for rx in SIGNALS.values() if rx.search(window))
        score += min(len(SIGNALS["age"].findall(window)), 3)
        score += min(len(SIGNALS["money"].findall(window)), 3)
        if score > best_score:
            best, best_score = window, score
    return best, best_score


def discover() -> list[tuple[str, str, str]]:
    """(channel, lender_slug, url) for every candidate page."""
    found: list[tuple[str, str, str]] = []
    for channel, (hub, pattern) in HUBS.items():
        if not robots_allows(hub):
            print(f"[{channel}] hub disallowed by robots.txt")
            continue
        status, html = polite_get(hub)
        slugs: dict[str, str] = {}
        for href in re.findall(r'href="([^"#?]+)"', html):
            url = urljoin(hub, href)
            m = pattern.match(url)
            if m and not NOT_A_LENDER.search(m.group(1)):
                slugs.setdefault(
                    m.group(1), url.rstrip("/") + ("/" if channel == "paisabazaar" else "")
                )
        print(f"[{channel}] hub HTTP {status}: {len(slugs)} lender pages discovered")
        found += [(channel, slug, url) for slug, url in sorted(slugs.items())]
    found += [("direct", slug, url) for slug, url in DIRECT.items()]
    return found


def assess(channel: str, slug: str, url: str, save_dir: Path | None) -> dict:
    row: dict = {"channel": channel, "lender": slug, "url": url}
    if not robots_allows(url):
        row["verdict"] = "robots_disallowed"
        return row
    status, html = polite_get(url)
    row["status"] = status
    if status in (403, 429) or (
        status == 200 and CHALLENGE.search(html[:3000]) and len(html) < 5000
    ):
        row["verdict"] = "blocked_by_site"  # bot wall: skip, never bypass
        return row
    if status != 200:
        row["verdict"] = f"http_{status}"
        return row
    text = visible_text(html)
    embedded = embedded_text(html)
    window, score = best_eligibility_window(text + "\n" + embedded)
    row.update(
        text_kb=len(text) // 1024,
        embedded_kb=len(embedded) // 1024,
        score=score,
        verdict="usable" if score >= 6 else "no_criteria_found",
    )
    if row["verdict"] == "usable" and save_dir:
        target = save_dir / channel / f"{slug}.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        # The isolated section: exactly what the LLM extraction step will read.
        target.with_suffix(".eligibility.txt").write_text(window, encoding="utf-8")
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-dir", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    rows = [assess(c, s, u, args.save_dir) for c, s, u in discover()]
    for r in rows:
        print(
            f"  {r['channel']:11} {r['lender']:28} {r.get('status', '-')!s:>4} "
            f"{r['verdict']:18} score={r.get('score', '-')} embedded={r.get('embedded_kb', '-')}KB"
        )
    usable = [r for r in rows if r["verdict"] == "usable"]
    by_channel: dict[str, int] = defaultdict(int)
    for r in usable:
        by_channel[r["channel"]] += 1
    lenders = {re.sub(r"-(bank|finserv|finance|first)$", "", r["lender"]) for r in usable}
    print(
        f"\nUSABLE pages: {len(usable)} of {len(rows)}  by channel: {dict(by_channel)}  "
        f"~distinct lenders: {len(lenders)}"
    )
    verdicts: dict[str, int] = defaultdict(int)
    for r in rows:
        verdicts[r["verdict"]] += 1
    print(f"verdicts: {dict(verdicts)}")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
