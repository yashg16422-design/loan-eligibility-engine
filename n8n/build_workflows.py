"""Generate the n8n workflow JSON files from tested sources.

Why generate: every Code node is assembled from n8n/code/*.js (unit-tested with
`node --test`) and the LLM prompt comes from n8n/prompts/*.md. Hand-copying code into
the n8n editor would let the running workflow drift from the tested code; generating
the JSON makes the repo the single source of truth. The output files in
n8n/workflows/ are the assignment deliverable and are imported into n8n with
`scripts/n8n-workflows.sh import`.

Credentials are referenced by id/name only. No secret ever appears in the output.

Usage: .venv/bin/python n8n/build_workflows.py
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "n8n" / "code"
OUT = ROOT / "n8n" / "workflows"
PROMPT_VERSION = "v2"
NORMALIZER_VERSION = 3  # keep equal to NORMALIZER_VERSION in n8n/code/normalize.js
# Part of every page hash: bumping the prompt or the normalizer re-processes each page once.
HASH_SALT = f"prompt={PROMPT_VERSION};normalizer={NORMALIZER_VERSION}"

WF_A = "LoanEngineWfA001"
WF_A1 = "LoanEngineWfA101"
WF_B = "LoanEngineWfB001"
WF_B1 = "LoanEngineWfB101"
WF_C = "LoanEngineWfC001"
WF_C1 = "LoanEngineWfC101"  # composes (never sends) the demo-capped users' emails, in batches
WF_E = "LoanEngineWfE001"  # error handler: settings.errorWorkflow of every other workflow
WF_E1 = "LoanEngineWfE101"  # drill: fails on purpose to prove the error path end to end
# Notification config (Workflow C). Not secrets: the SES-verified sender and test aliases.
# Mail NEVER goes to CSV addresses: email.js picks one of these and refuses anything else.
SES_FROM = "yashg16422@gmail.com"
TEST_ALIASES = [
    "yashg16422+one@gmail.com",
    "yashg16422+two@gmail.com",
    "yashg16422+three@gmail.com",
]
DEMO_MAX_EMAILS = 5  # SES sandbox: 200/day, 1/s. The rest are recorded as skipped_demo.
COMPOSE_BATCH = 500  # C1: emails composed per sub-workflow execution (bounded memory)
REMATCH_LATE_COMPILES = True  # B: re-match products whose criteria compiled after a failure
CRAWL_DROP_ALERT_PCT = 30  # Workflow A alerts when a channel's usable pages drop by more than this
COMPILE_PROMPT_VERSION = "compile_v1"
# Bedrock list price used for the cost ESTIMATE in pipeline_runs (USD per 1k tokens).
NOVA_PRO_USD_PER_1K = {"input": 0.0008, "output": 0.0032}
REGION = "ap-southeast-2"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 LoanEligibilityEngine-assignment/1.0"
)
# Credential ids as created in the n8n UI (README §5). Ids, not secrets.
# Credential REFERENCES (id + name), never secrets. The ids belong to the n8n instance the
# credentials were created in; on a fresh n8n, create the three credentials (README §5) and
# set N8N_CRED_PG / N8N_CRED_AWS / N8N_CRED_WEBHOOK to their ids before regenerating.
PG = {
    "postgres": {
        "id": os.environ.get("N8N_CRED_PG", "PkRN0GO4XtFXA9pL"),
        "name": "RDS app (n8n_workflows)",
    }
}
AWS = {
    "awsAssumeRole": {
        "id": os.environ.get("N8N_CRED_AWS", "fa286DA3YraErW57"),
        "name": "AWS n8n role (assume)",
    }
}
WEBHOOK_AUTH = {
    "httpHeaderAuth": {
        "id": os.environ.get("N8N_CRED_WEBHOOK", "qaXP0OsyRtnbitga"),
        "name": "Ingest webhook secret",
    }
}


# One line under every node on the canvas (n8n `notes` + `notesInFlow`): what it does and why.
# tests/unit/test_workflows.py checks that every work node has one, at most 120 characters.
NODE_NOTES: dict[str, dict[str, str]] = {
    WF_A: {
        "Every day 06:00 IST": "The assignment's schedule trigger: one crawl a day.",
        "Run now (demo)": "Manual trigger for demos; same path as the schedule.",
        "Start run": "New crawl run_id + the enabled crawl_sources rows (sites are config, not code).",
        "Origins to check": "One item per site, so each robots.txt is fetched once.",
        "Fetch robots.txt": "GET /robots.txt per site; errors never stop the crawl.",
        "Robots rules": "RFC 9309 parser (robots.js) decides every URL before it is fetched.",
        "Hub sources": "Comparison-site hub pages that list lenders.",
        "Fetch hub pages": "GET each hub page (1 request/s).",
        "Discover pages": "Lender links from hubs + direct bank pages, interleaved round-robin across sites.",
        "robots.txt allows?": "Disallowed pages are logged and never fetched.",
        "Log robots-disallowed": "Records each skipped URL as robots_disallowed in crawl_runs.",
        "Every 5 pages": "Loop: batches of 5 pages go to A1, so results are written as the crawl goes.",
        "Batch → one item": "Packs the 5 pages into one item for the sub-workflow call.",
        "Process batch (A1)": "Fetch, isolate, hash, LLM only if changed, verify, upsert (sub-workflow A1).",
        "Run summary": "Collects the batch results into one item for Finish run.",
        "Finish run": "Deactivates products gone from healthy pages; counts pages, products, tokens.",
        "Products changed?": "New or changed products are re-matched against every user.",
        "Re-match changed products (B)": "Calls B in product mode with the changed product ids.",
        "Crawl health": "Usable pages per channel vs the previous crawl: a >30% drop means a site changed.",
        "Crawl degraded?": "Alert at most once a day; the drop is always logged in workflow_errors.",
        "Email crawl alert (SES)": "Tells the operator which channel degraded (test alias only).",
    },
    WF_A1: {
        "From A (batch)": "Called by A with up to 5 pages and the crawl run_id.",
        "Expand pages": "One item per page.",
        "Fetch page (1 req/s)": "Polite GET (browser-compatible UA, 1 req/s, retries); optional renderer.",
        "Classify fetch": "ok / blocked (403, 429, challenge: skipped, never bypassed) / failed.",
        "Live fetch failed?": "Failed pages fall back to their saved S3 snapshot.",
        "S3 fixture": "Reads the page snapshot from S3 (the instance role, no keys).",
        "Use fixture": "Marks the page as fixture so the run stays honest about its source.",
        "Pages with HTML": "Joins live and fixture pages back into one stream.",
        "Isolate sections": "Scores candidate windows to find the eligibility and rate sections.",
        "Hash sections": "SHA-256 of the sections + prompt/normalizer version.",
        "URLs → one query": "One lookup for all pages instead of one query per page.",
        "Known hashes": "Last stored hash per page.",
        "Mark changed": "Compares hashes: unchanged pages skip the LLM entirely.",
        "Changed?": "Only changed pages go to Nova Pro.",
        "Build Nova request": "ONE batched Converse request for all changed pages of the batch.",
        "Nova Pro (Converse)": "Amazon Bedrock Nova Pro, temperature 0, via the Assume Role credential.",
        "Verify + normalize": "Every criterion must quote the page; numbers parsed deterministically.",
        "Upsert products + log pages": "One SQL statement per batch + a crawl_runs row per page.",
        "Unchanged → bookkeeping": "No LLM: prepares last_seen updates for unchanged pages.",
        "Touch last_seen + log pages": "Marks products still seen; logs pages as unchanged.",
    },
    WF_B: {
        "Run now (demo)": "Manual trigger: matches the newest unmatched upload.",
        "Ingest complete (webhook)": "Called by the ingest Lambda after COMMIT; Header Auth; answers at once.",
        "Sweeper every 10 min": "Recovery: picks up jobs whose webhook was missed or whose run died.",
        "From A (product mode)": "Re-match every user against new or changed products.",
        "Webhook → request": "Validates the body: a non-UUID job_id never reaches SQL.",
        "Jobs waiting for matching": "sweeper.sql: missed, stale or failed jobs (max 3 tries).",
        "Products → request": "Turns A's product ids into a product-mode request.",
        "Claim job + start run": "Atomic claim: a duplicate webhook racing the sweeper can never double-match.",
        "Match (B1)": "Runs the Treasure Hunt for this run (sub-workflow B1).",
        "Matching failed?": "A failed or stopped B1 run marks the job FAILED instead of hanging.",
        "Mark job failed": "Visible in the upload UI; the sweeper retries it later.",
        "Notify users (C)": "Emails users with new matches (sub-workflow C).",
        "Runs waiting for emails": "Runs that wrote matches but never recorded emails (n8n died mid-run).",
        "Prove again before emailing": "Re-checks every pair of that run before anyone is emailed.",
        "Proof still passes?": "Only an exact run is emailed; a failed proof leaves it for a human.",
        "Mark run recovered": "Records the run as done, noting the sweeper recovered it.",
        "Finish emails (C)": "C picks up where it stopped; users already emailed are skipped.",
        "Products compiled late": "Products whose criteria compiled for the first time in this run.",
        "Re-match them?": "Earlier users hold a provisional 'may qualify' for them: decide again.",
        "Re-match all users (B, product mode)": "Product-mode run for those products; it compiles nothing, so it never loops.",
    },
    WF_B1: {
        "From B (run)": "Called by B with the claimed run_id.",
        "Criteria to compile": "Distinct criteria texts not yet compiled (cache misses only).",
        "Batches of 10 texts": "10 texts per Nova call; usually 0 after the first run.",
        "Anything to compile?": "Skips the LLM entirely when every text is cached.",
        "Build compile request": "Asks Nova Pro to turn free-text criteria into checkable rules.",
        "Nova Pro · compile": "Bedrock Converse, temperature 0; LLM cost scales with texts, not users.",
        "Validate compiled rules": "Each rule re-checked against its source text; failures become requirements.",
        "Save compiled rules": "Caches rules by text hash; records calls, tokens, cost on the run.",
        "Stage 1+2 · classes & decisions": "Cut points → equivalence classes; decide class x product in SQL.",
        "Refresh planner stats": "ANALYZE the bulk-written tables so Stage 3 gets a good plan.",
        "Pre-write proof": "Naive per-user check of the class decisions BEFORE any match is written.",
        "Pre-write passed?": "Any mismatch stops the run here: zero matches written.",
        "Stop: pre-write proof failed": "Throws, so B marks the job failed and C never runs.",
        "Stage 3 · expand, score, diff": "Expand to users, fit score, diff vs active matches (one transaction).",
        "Correctness proof": "Re-checks every stored pair against the naive evaluation.",
        "Proof passed?": "0 mismatches required before the run is done.",
        "Stop: proof failed": "Throws: nothing marked done, nobody emailed, E alerts.",
        "Finish run": "Marks the run done and returns every Treasure Hunt counter.",
        "Treasure Hunt funnel": "One item: pairs → classes → decisions → LLM calls → matches → mismatches.",
    },
    WF_C: {
        "Run now (latest run)": "Manual trigger for the newest run with new matches.",
        "Latest run with new matches": "Finds that run.",
        "From B (run)": "Called by B after a successful match run.",
        "Run to notify": "The run being notified, read by every later node.",
        "Users to email": "Users with new matches: top 5 picks, one per lender, best platform.",
        "Anyone to email?": "Nobody left (already sent) goes straight to recording the run.",
        "Sign dashboard links": "One call to the api Lambda: a signed 14-day dashboard link per user.",
        "Compose emails": "email.js: personal HTML + text; recipient guarded to the test aliases.",
        "One email at a time": "Loop: one email per iteration.",
        "Send via AWS SES": "The AWS SES node with the Assume Role credential (no keys).",
        "Delivery result": "SES message id, or the error.",
        "Record this send": "Stored immediately: a crash mid-loop never emails anyone twice.",
        "1 email / second (SES sandbox)": "Paces the loop for the SES sandbox rate.",
        "All results -> one item": "Collapses the loop output so the summary runs once.",
        "Record notifications": "Everyone else is recorded as skipped_demo; counters set from the table.",
        "Compose the rest (C1)": "Builds and stores every other user's email, 500 per sub-workflow run.",
        "More to compose?": "Loops until every user's email is stored (bounded: at most 200 batches).",
    },
    WF_C1: {
        "From C (run)": "Called by C with the run_id, once per batch.",
        "Next users to compose": "Up to 500 users whose send was skipped and whose email is not built yet.",
        "Compose (no send)": "email.js builds each personal email (subject + text); nothing is sent.",
        "Save composed emails": "Stores them on the notification rows; returns how many remain.",
    },
    WF_E: {
        "Drill: simulate an error": "Manual trigger replaying a sample payload through the same nodes.",
        "Sample error payload": "A realistic n8n error payload for the drill.",
        "On workflow error": "n8n starts E when any production execution of A, A1, B, B1 or C fails.",
        "Summarize error": "errors.js: one record from both n8n payload shapes; never throws.",
        "Record error": "Stores it in workflow_errors; alert at most once per workflow per 30 min.",
        "Alert due?": "Rate limit, so a failing schedule cannot drain the SES quota.",
        "Email alert (SES)": "Alert to the test alias; a failed alert never fails the handler.",
    },
    WF_E1: {
        "Run drill": "Scheduled while the drill is published (scripts/n8n-workflows.sh drill).",
        "Fail on purpose": "Throws, to prove that Workflow E records and alerts.",
    },
}


def stack_output(key: str) -> str:
    return subprocess.run(
        [str(ROOT / "scripts" / "stack-output.sh"), key],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def js(*modules: str, entry: str) -> str:
    """A Code node body: the tested module files, then the node's entry snippet."""
    parts = [(CODE / m).read_text() for m in modules]
    return "\n\n".join([*parts, "// ---- n8n entry " + "-" * 60, entry.strip()]) + "\n"


def sql_file(name: str) -> str:
    """A query from sql/matching/: the same file the integration tests run."""
    return (ROOT / "sql" / "matching" / name).read_text()


def prompt_constants(
    file: str = f"extract_criteria_{PROMPT_VERSION}", version: str = PROMPT_VERSION
) -> str:
    text = (ROOT / "n8n" / "prompts" / f"{file}.md").read_text()
    system = text.split("## System prompt")[1].split("## User message template")[0].strip()
    # Cut at the first template loop ({{#each pages}} / {{#each texts}}): the loop is only
    # documentation; the Code node appends the real blocks.
    head = text.split("## User message template")[1].split("{{#each")[0].strip()
    return (
        f"const PROMPT_VERSION = {json.dumps(version)};\n"
        f"const PROMPT = {{ system: {json.dumps(system)}, head: {json.dumps(head)} }};\n"
    )


class Flow:
    """Tiny builder for n8n workflow JSON (nodes + connections)."""

    def __init__(
        self, wf_id: str, name: str, description: str, error_workflow: str | None = WF_E
    ) -> None:
        self.wf_id, self.name, self.description = wf_id, name, description
        # Any failed production execution (schedule, webhook, sub-workflow) runs Workflow E.
        # E itself has none: an error handler that errors must not call itself in a loop.
        self.error_workflow = error_workflow
        self.nodes: list[dict[str, Any]] = []
        self.connections: dict[str, Any] = {}

    def add(
        self,
        name: str,
        node_type: str,
        version: float,
        params: dict,
        pos: tuple[int, int],
        **extra: Any,
    ) -> str:
        node = {
            "parameters": params,
            "name": name,
            "type": node_type,
            "typeVersion": version,
            "position": list(pos),
            "id": f"{self.wf_id}-{len(self.nodes):02d}",
        }
        node.update(extra)
        self.nodes.append(node)
        return name

    def link(self, src: str, dst: str, out: int = 0, inp: int = 0) -> None:
        outs = self.connections.setdefault(src, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": dst, "type": "main", "index": inp})

    def sticky(self, text: str, pos: tuple[int, int], size: tuple[int, int] = (420, 240)) -> None:
        self.add(
            f"Note {len(self.nodes)}",
            "n8n-nodes-base.stickyNote",
            1,
            {"content": text, "width": size[0], "height": size[1]},
            pos,
        )

    def build(self) -> dict[str, Any]:
        notes = NODE_NOTES.get(self.wf_id, {})
        for node in self.nodes:
            if node["type"] != "n8n-nodes-base.stickyNote" and node["name"] in notes:
                node["notes"] = notes[node["name"]]
                node["notesInFlow"] = True
        return {
            "id": self.wf_id,
            "name": self.name,
            "active": False,
            "nodes": self.nodes,
            "connections": self.connections,
            "settings": {
                "executionOrder": "v1",
                "timezone": "Asia/Kolkata",
                "saveDataErrorExecution": "all",
                "saveDataSuccessExecution": "all",
                **({"errorWorkflow": self.error_workflow} if self.error_workflow else {}),
            },
            "meta": {"description": self.description},
            "pinData": {},
        }


# ---------------------------------------------------------------- node helpers


def http_text(url: str, **opts: Any) -> dict:
    """HTTP GET returning the full response as text, never throwing on HTTP status."""
    return {
        "url": url,
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "User-Agent", "value": USER_AGENT},
                {"name": "Accept", "value": "text/html,application/xhtml+xml,*/*;q=0.8"},
            ]
        },
        "options": {
            "timeout": opts.get("timeout", 20000),
            "response": {
                "response": {"fullResponse": True, "neverError": True, "responseFormat": "text"}
            },
            **(
                {"batching": {"batch": {"batchSize": 1, "batchInterval": opts["interval"]}}}
                if "interval" in opts
                else {}
            ),
        },
    }


def pg_query(query: str, params: str | None = None) -> dict:
    p: dict[str, Any] = {"operation": "executeQuery", "query": query.strip(), "options": {}}
    if params:
        p["options"]["queryReplacement"] = params
    return p


def if_true(expr: str) -> dict:
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
            "conditions": [
                {
                    "id": "c1",
                    "leftValue": expr,
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }
            ],
            "combinator": "and",
        },
        "options": {},
    }


CODE_T, HTTP_T, PG_T, IF_T = (
    "n8n-nodes-base.code",
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.postgres",
    "n8n-nodes-base.if",
)


# ---------------------------------------------------------------- Workflow A1 (batch)


def workflow_a1(bucket: str) -> dict:
    f = Flow(
        WF_A1,
        "A1 · Process page batch (sub-workflow)",
        "Fetch → isolate → hash → (Nova Pro only if changed) → verify/normalize → upsert, for ≤5 pages.",
    )
    f.sticky(
        "## A1 · Process one batch (≤5 pages)\nCalled by **A · Loan product discovery** for each batch, so "
        "results are written batch by batch (streaming).\n\n- **Unchanged pages** (same SHA-256 of the "
        "eligibility+rate sections) → zero LLM calls.\n- **Changed pages** → ONE Nova Pro call for the "
        "whole batch, then evidence verification + deterministic normalization.\n- 403/429/challenge = "
        "**blocked**, skipped (never bypassed). Other failures → S3 fixture.",
        (-40, -380),
        (560, 300),
    )

    f.add(
        "From A (batch)",
        "n8n-nodes-base.executeWorkflowTrigger",
        1.1,
        {"inputSource": "passthrough"},
        (0, 0),
    )
    f.add(
        "Expand pages",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const { run_id, pages } = $input.first().json;
return pages.map((p) => ({ json: { ...p, run_id } }));
"""
            )
        },
        (220, 0),
    )
    # One HTTP node for both fetch modes: static pages are a plain GET; pages configured
    # fetch_mode=rendered go to the optional headless renderer (off by default).
    f.add(
        "Fetch page (1 req/s)",
        HTTP_T,
        4.2,
        {
            **http_text(
                "={{ $json.fetch_mode === 'rendered' ? 'http://renderer:3000/render' : $json.url }}",
                interval=1000,
            ),
            "method": "={{ $json.fetch_mode === 'rendered' ? 'POST' : 'GET' }}",
            "sendBody": "={{ $json.fetch_mode === 'rendered' }}",
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ url: $json.url, timeout_ms: 30000 }) }}",
        },
        (440, 0),
        retryOnFail=True,
        maxTries=2,
        waitBetweenTries=3000,
        onError="continueRegularOutput",
    )
    f.add(
        "Classify fetch",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
// ok = usable HTML; blocked = the site refuses bots (skip, never bypass); failed = try the S3 fixture.
const CHALLENGE = /captcha|verify you are human|are you a robot|request forbidden|access denied|attention required|checking your browser|unusual traffic/i;
return $input.all().map((item, i) => {
  const page = $('Expand pages').itemMatching(i).json;
  const r = item.json;
  let status = Number(r.statusCode || 0);
  let html = typeof r.body === 'string' ? r.body : (typeof r.data === 'string' ? r.data : '');
  if (page.fetch_mode === 'rendered' && status === 200) {
    try { const j = JSON.parse(html); status = Number(j.status || 0); html = j.challenge ? '' : (j.html || ''); if (j.challenge) status = 403; } catch { status = 0; html = ''; }
  }
  const blocked = status === 403 || status === 429 || (status === 200 && html.length < 5000 && CHALLENGE.test(html.slice(0, 3000)));
  const fetch_status = blocked ? 'blocked' : (status === 200 && html.length > 500 ? 'ok' : 'failed');
  return { json: { ...page, http_status: status, fetch_status, html: fetch_status === 'ok' ? html : '' } };
});
"""
            )
        },
        (660, 0),
    )
    f.add(
        "Live fetch failed?", IF_T, 2, if_true("={{ $json.fetch_status === 'failed' }}"), (880, 0)
    )
    f.add(
        "S3 fixture",
        HTTP_T,
        4.2,
        {
            **http_text(
                f"=https://{bucket}.s3.{REGION}.amazonaws.com/fixtures/{{{{ $json.channel }}}}/{{{{ $json.lender_slug }}}}.html"
            ),
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "awsAssumeRole",
        },
        (1100, -120),
        credentials=AWS,
        onError="continueRegularOutput",
    )
    f.add(
        "Use fixture",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
return $input.all().map((item, i) => {
  const page = $('Classify fetch').itemMatching(i).json;
  const ok = Number(item.json.statusCode) === 200;
  const html = ok ? (item.json.body ?? item.json.data ?? '') : '';
  return { json: { ...page, fetch_status: ok ? 'fixture' : 'failed', html } };
});
"""
            )
        },
        (1320, -120),
    )
    f.add("Pages with HTML", "n8n-nodes-base.merge", 3, {}, (1540, 0))
    f.add(
        "Isolate sections",
        CODE_T,
        2,
        {
            "jsCode": js(
                "sections.js",
                entry="""
return $input.all().map((item) => {
  const { html, ...page } = item.json; // drop raw HTML: large and no longer needed
  if (!html) return { json: { ...page, crawl_status: page.fetch_status, eligibility_text: '', rates_text: '' } };
  const s = extractSections(html);
  // A page that no longer has a recognisable section is treated as failed (likely a
  // layout change): its existing products are kept, never wiped by a bad parse.
  if (!s.section_found) return { json: { ...page, ...s, crawl_status: 'failed', error: 'no eligibility section found (layout change?)' } };
  return { json: { ...page, ...s, crawl_status: page.fetch_status } };
});
""",
            )
        },
        (1760, 0),
    )
    f.add(
        "Hash sections",
        "n8n-nodes-base.crypto",
        1,
        {
            "action": "hash",
            "type": "SHA256",
            "dataPropertyName": "criteria_hash",
            "value": f"={{{{ '{HASH_SALT}\\n' + ($json.eligibility_text || '') + '\\n' + ($json.rates_text || '') }}}}",
        },
        (1980, 0),
    )
    f.add(
        "URLs → one query",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
return [{ json: { urls: $input.all().map((i) => i.json.url) } }];
"""
            )
        },
        (2200, 0),
    )
    f.add(
        "Known hashes",
        PG_T,
        2.5,
        pg_query(
            """
SELECT source_url, max(criteria_hash) AS criteria_hash
FROM loan_products
WHERE is_active AND source_url IN (SELECT jsonb_array_elements_text($1::jsonb))
GROUP BY source_url
""",
            "={{ [ JSON.stringify($json.urls) ] }}",
        ),
        (2420, 0),
        credentials=PG,
        alwaysOutputData=True,
    )
    f.add(
        "Mark changed",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const known = Object.fromEntries($input.all().filter((i) => i.json.source_url).map((i) => [i.json.source_url, i.json.criteria_hash]));
return $('Hash sections').all().map((i) => {
  const p = i.json;
  const usable = p.crawl_status === 'ok' || p.crawl_status === 'fixture';
  return { json: { ...p, page_id: p.page_id || `${p.channel}:${p.lender_slug}`, changed: usable && known[p.url] !== p.criteria_hash } };
});
"""
            )
        },
        (2640, 0),
    )
    f.add("Changed?", IF_T, 2, if_true("={{ $json.changed }}"), (2860, 0))

    # ---- changed: one batched LLM call
    f.add(
        "Build Nova request",
        CODE_T,
        2,
        {
            "jsCode": js(
                "structured.js",
                "llm.js",
                entry=prompt_constants()
                + """
const pages = $input.all().map((i) => i.json);
return [{ json: { pages, request: buildConverseRequest(pages, PROMPT), prompt_version: PROMPT_VERSION } }];
""",
            )
        },
        (3080, -160),
    )
    f.add(
        "Nova Pro (Converse)",
        HTTP_T,
        4.2,
        {
            "method": "POST",
            "url": f"https://bedrock-runtime.{REGION}.amazonaws.com/model/amazon.nova-pro-v1:0/converse",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "awsAssumeRole",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json.request) }}",
            "options": {"timeout": 120000},
        },
        (3300, -160),
        credentials=AWS,
        retryOnFail=True,
        maxTries=3,
        waitBetweenTries=5000,
        onError="continueRegularOutput",
    )
    f.add(
        "Verify + normalize",
        CODE_T,
        2,
        {
            "jsCode": js(
                "structured.js",
                "llm.js",
                "normalize.js",
                entry="""
const { pages, prompt_version } = $('Build Nova request').first().json;
const res = $input.first().json;
const parsed = parseConverseResponse(res.error ? { message: res.error.message || JSON.stringify(res.error) } : res, pages.map((p) => p.page_id));
const share = (n) => Math.round(n / Math.max(pages.length, 1)); // tokens apportioned per page
const products = [];
const logs = [];
for (const p of pages) {
  const base = { run_id: p.run_id, url: p.url, channel: p.channel, lender_slug: p.lender_slug, http_status: p.http_status,
    changed: true, llm_input_tokens: share(parsed.inputTokens), llm_output_tokens: share(parsed.outputTokens) };
  const extraction = parsed.extractions[p.page_id];
  if (!extraction) { // keep the old products; no hash stored, so the page is retried next run
    logs.push({ ...base, status: 'failed', products_found: 0, error: `LLM: ${parsed.error || 'no extraction for page'}` });
    continue;
  }
  const seen = new Set();
  const rows = toProducts({ ...p, extraction }).filter((r) => !seen.has(r.product_name) && seen.add(r.product_name));
  rows.forEach((r) => products.push({ ...r, criteria_hash: p.criteria_hash, raw_extracted: { ...r.raw_extracted, prompt_version } }));
  logs.push({ ...base, status: p.crawl_status, products_found: rows.length, error: null });
}
return [{ json: { products, pages: logs } }];
""",
            )
        },
        (3520, -160),
    )
    f.add(
        "Upsert products + log pages",
        PG_T,
        2.5,
        pg_query(
            """
WITH incoming AS (
  SELECT * FROM jsonb_to_recordset($1::jsonb) AS r(
    lender text, lender_key text, channel text, source_url text, product_name text, product_url text,
    interest_rate_min numeric, interest_rate_max numeric, rate_type text, min_monthly_income int,
    min_credit_score int, max_credit_score int, min_age int, max_age int, employment_types jsonb,
    loan_amount_min bigint, loan_amount_max bigint, tenure_months_max int, other_criteria_text text,
    verification text, raw_extracted jsonb, criteria_hash text)
), upserted AS (
  INSERT INTO loan_products AS p (
    lender, lender_key, channel, source_url, product_name, product_url, interest_rate_min,
    interest_rate_max, rate_type, min_monthly_income, min_credit_score, max_credit_score, min_age,
    max_age, employment_types, loan_amount_min, loan_amount_max, tenure_months_max,
    other_criteria_text, verification, raw_extracted, criteria_json, criteria_hash, is_active,
    first_seen_at, last_seen_at, last_changed_at)
  SELECT lender, lender_key, channel, source_url, product_name, product_url, interest_rate_min,
    interest_rate_max, coalesce(rate_type, 'unknown'), min_monthly_income, min_credit_score,
    max_credit_score, min_age, max_age,
    CASE WHEN jsonb_typeof(employment_types) = 'array'
         THEN ARRAY(SELECT jsonb_array_elements_text(employment_types)) END,
    loan_amount_min, loan_amount_max, tenure_months_max, other_criteria_text, verification,
    raw_extracted,
    jsonb_build_object('min_age', min_age, 'max_age', max_age, 'min_monthly_income', min_monthly_income,
      'min_credit_score', min_credit_score, 'employment_types', employment_types,
      'other_criteria_text', other_criteria_text),
    criteria_hash, true, now(), now(), now()
  FROM incoming
  ON CONFLICT (source_url, product_name) DO UPDATE SET
    lender = EXCLUDED.lender, lender_key = EXCLUDED.lender_key, channel = EXCLUDED.channel,
    product_url = EXCLUDED.product_url, interest_rate_min = EXCLUDED.interest_rate_min,
    interest_rate_max = EXCLUDED.interest_rate_max, rate_type = EXCLUDED.rate_type,
    min_monthly_income = EXCLUDED.min_monthly_income, min_credit_score = EXCLUDED.min_credit_score,
    max_credit_score = EXCLUDED.max_credit_score, min_age = EXCLUDED.min_age, max_age = EXCLUDED.max_age,
    employment_types = EXCLUDED.employment_types, loan_amount_min = EXCLUDED.loan_amount_min,
    loan_amount_max = EXCLUDED.loan_amount_max, tenure_months_max = EXCLUDED.tenure_months_max,
    other_criteria_text = EXCLUDED.other_criteria_text, verification = EXCLUDED.verification,
    raw_extracted = EXCLUDED.raw_extracted, criteria_json = EXCLUDED.criteria_json,
    criteria_hash = EXCLUDED.criteria_hash, is_active = true, last_seen_at = now(),
    -- "changed" = the criteria really changed, so Workflow B re-matches only those products.
    last_changed_at = CASE WHEN p.criteria_json IS DISTINCT FROM EXCLUDED.criteria_json
                           THEN now() ELSE p.last_changed_at END
  RETURNING (xmax = 0) AS inserted
), logged AS (
  INSERT INTO crawl_runs (run_id, source_url, channel, lender_slug, status, http_status, changed,
                          products_found, llm_input_tokens, llm_output_tokens, error, finished_at)
  SELECT run_id::uuid, url, channel, lender_slug, status, http_status, changed, products_found,
         llm_input_tokens, llm_output_tokens, error, now()
  FROM jsonb_to_recordset($2::jsonb) AS l(run_id text, url text, channel text, lender_slug text,
       status text, http_status int, changed boolean, products_found int, llm_input_tokens int,
       llm_output_tokens int, error text)
  ON CONFLICT (run_id, source_url) DO NOTHING
  RETURNING 1
)
SELECT (SELECT count(*) FROM upserted WHERE inserted) AS products_inserted,
       (SELECT count(*) FROM upserted WHERE NOT inserted) AS products_updated,
       (SELECT count(*) FROM logged) AS pages_logged
""",
            "={{ [ JSON.stringify($json.products), JSON.stringify($json.pages) ] }}",
        ),
        (3740, -160),
        credentials=PG,
    )

    # ---- unchanged / blocked / failed: no LLM, just bookkeeping
    f.add(
        "Unchanged → bookkeeping",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const pages = $input.all().map((i) => i.json);
const fine = (p) => p.crawl_status === 'ok' || p.crawl_status === 'fixture';
return [{ json: {
  touch: pages.filter(fine).map((p) => p.url),
  pages: pages.map((p) => ({ run_id: p.run_id, url: p.url, channel: p.channel, lender_slug: p.lender_slug,
    status: p.crawl_status === 'ok' ? 'unchanged' : p.crawl_status, http_status: p.http_status, changed: false,
    products_found: null, llm_input_tokens: 0, llm_output_tokens: 0, error: p.error || null })),
} }];
"""
            )
        },
        (3080, 160),
    )
    f.add(
        "Touch last_seen + log pages",
        PG_T,
        2.5,
        pg_query(
            """
WITH touched AS (
  UPDATE loan_products SET last_seen_at = now()
  WHERE is_active AND source_url IN (SELECT jsonb_array_elements_text($1::jsonb))
  RETURNING 1
), logged AS (
  INSERT INTO crawl_runs (run_id, source_url, channel, lender_slug, status, http_status, changed,
                          products_found, llm_input_tokens, llm_output_tokens, error, finished_at)
  SELECT run_id::uuid, url, channel, lender_slug, status, http_status, changed, products_found,
         llm_input_tokens, llm_output_tokens, error, now()
  FROM jsonb_to_recordset($2::jsonb) AS l(run_id text, url text, channel text, lender_slug text,
       status text, http_status int, changed boolean, products_found int, llm_input_tokens int,
       llm_output_tokens int, error text)
  ON CONFLICT (run_id, source_url) DO NOTHING
  RETURNING 1
)
SELECT (SELECT count(*) FROM touched) AS products_touched, (SELECT count(*) FROM logged) AS pages_logged
""",
            "={{ [ JSON.stringify($json.touch), JSON.stringify($json.pages) ] }}",
        ),
        (3300, 160),
        credentials=PG,
    )

    for a, b in [
        ("From A (batch)", "Expand pages"),
        ("Expand pages", "Fetch page (1 req/s)"),
        ("Fetch page (1 req/s)", "Classify fetch"),
        ("Classify fetch", "Live fetch failed?"),
        ("S3 fixture", "Use fixture"),
        ("Pages with HTML", "Isolate sections"),
        ("Isolate sections", "Hash sections"),
        ("Hash sections", "URLs → one query"),
        ("URLs → one query", "Known hashes"),
        ("Known hashes", "Mark changed"),
        ("Mark changed", "Changed?"),
        ("Build Nova request", "Nova Pro (Converse)"),
        ("Nova Pro (Converse)", "Verify + normalize"),
        ("Verify + normalize", "Upsert products + log pages"),
        ("Unchanged → bookkeeping", "Touch last_seen + log pages"),
    ]:
        f.link(a, b)
    f.link("Live fetch failed?", "S3 fixture", out=0)
    f.link("Live fetch failed?", "Pages with HTML", out=1, inp=1)
    f.link("Use fixture", "Pages with HTML", inp=0)
    f.link("Changed?", "Build Nova request", out=0)
    f.link("Changed?", "Unchanged → bookkeeping", out=1)
    return f.build()


# ---------------------------------------------------------------- Workflow A (parent)


def workflow_a() -> dict:
    f = Flow(
        WF_A,
        "A · Loan product discovery (crawler)",
        "Daily crawl of lender pages (direct banks + BankBazaar + Paisabazaar) into loan_products.",
    )
    f.sticky(
        "## A · Loan product discovery\n**Schedule:** daily 06:00 IST (+ manual run for demos).\n\n"
        "1. Sources come from the `crawl_sources` table (config, not code).\n2. robots.txt is fetched "
        "per site and obeyed.\n3. Hubs are crawled for lender links; pages are interleaved across "
        "sites (polite).\n4. Pages go in batches of 5 to **A1**, which writes results as it goes.\n"
        "5. Finish: deactivate products that vanished from pages crawled OK; report.\n6. Crawl health: "
        "a channel whose usable pages drop >30% (a site redesign) is logged and alerts once a day.",
        (-40, -380),
        (560, 320),
    )
    f.add(
        "Every day 06:00 IST",
        "n8n-nodes-base.scheduleTrigger",
        1.2,
        {"rule": {"interval": [{"field": "cronExpression", "expression": "0 6 * * *"}]}},
        (0, -80),
    )
    f.add("Run now (demo)", "n8n-nodes-base.manualTrigger", 1, {}, (0, 80))
    f.add(
        "Start run",
        PG_T,
        2.5,
        pg_query("""
SELECT gen_random_uuid()::text AS run_id, now() AS started_at,
       COALESCE((SELECT json_agg(s ORDER BY s.source_id) FROM crawl_sources s WHERE s.enabled), '[]'::json) AS sources
"""),
        (220, 0),
        credentials=PG,
    )
    f.add(
        "Origins to check",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const { sources } = $input.first().json;
const origins = [...new Set(sources.map((s) => s.url.match(/^https?:\\/\\/[^/]+/i)[0]))];
return origins.map((origin) => ({ json: { origin, robots_url: `${origin}/robots.txt` } }));
"""
            )
        },
        (440, 0),
    )
    f.add(
        "Fetch robots.txt",
        HTTP_T,
        4.2,
        http_text("={{ $json.robots_url }}", timeout=15000),
        (660, 0),
        retryOnFail=True,
        maxTries=2,
        onError="continueRegularOutput",
    )
    f.add(
        "Robots rules",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
// One map origin -> {status, body}. An unreachable robots.txt (status 0) means "disallow all".
const robots = {};
$input.all().forEach((item, i) => {
  const { origin } = $('Origins to check').itemMatching(i).json;
  const r = item.json;
  robots[origin] = { status: Number(r.statusCode || 0), body: typeof r.body === 'string' ? r.body : (r.data || '') };
});
return [{ json: { robots } }];
"""
            )
        },
        (880, 0),
    )
    f.add(
        "Hub sources",
        CODE_T,
        2,
        {
            "jsCode": js(
                "robots.js",
                entry="""
const { sources } = $('Start run').first().json;
const { robots } = $input.first().json;
const origin = (u) => u.match(/^https?:\\/\\/[^/]+/i)[0];
return sources.filter((s) => s.discovery === 'hub' && isAllowed(s.url, robots[origin(s.url)])).map((s) => ({ json: s }));
""",
            )
        },
        (1100, 0),
        alwaysOutputData=True,
    )
    f.add(
        "Fetch hub pages",
        HTTP_T,
        4.2,
        http_text("={{ $json.url }}", interval=1500),
        (1320, 0),
        retryOnFail=True,
        maxTries=3,
        waitBetweenTries=3000,
        onError="continueRegularOutput",
    )
    f.add(
        "Discover pages",
        CODE_T,
        2,
        {
            "jsCode": js(
                "robots.js",
                "discover.js",
                entry="""
const run = $('Start run').first().json;
const { robots } = $('Robots rules').first().json;
const hubHtml = {};
$input.all().forEach((item, i) => {
  const hub = $('Hub sources').itemMatching(i).json;
  const r = item.json;
  if (hub && hub.source_id && Number(r.statusCode) === 200) hubHtml[hub.source_id] = r.body ?? r.data ?? '';
});
const origin = (u) => u.match(/^https?:\\/\\/[^/]+/i)[0];
return planPages(run.sources, hubHtml).map((p, seq) => ({ json: {
  ...p, run_id: run.run_id, seq, page_id: `${p.channel}:${p.lender_slug}`,
  robots_allowed: isAllowed(p.url, robots[origin(p.url)]),
} }));
""",
            )
        },
        (1540, 0),
    )
    f.add("robots.txt allows?", IF_T, 2, if_true("={{ $json.robots_allowed }}"), (1760, 0))
    f.add(
        "Log robots-disallowed",
        PG_T,
        2.5,
        pg_query(
            """
INSERT INTO crawl_runs (run_id, source_url, channel, lender_slug, status, error, finished_at)
VALUES ($1::uuid, $2, $3, $4, 'robots_disallowed', 'robots.txt disallows this URL: never fetched', now())
ON CONFLICT (run_id, source_url) DO NOTHING
""",
            "={{ [ $json.run_id, $json.url, $json.channel, $json.lender_slug ] }}",
        ),
        (1980, 200),
        credentials=PG,
    )
    f.add(
        "Every 5 pages",
        "n8n-nodes-base.splitInBatches",
        3,
        {"batchSize": 5, "options": {}},
        (1980, -40),
    )
    f.add(
        "Batch → one item",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const pages = $input.all().map((i) => i.json);
return [{ json: { run_id: pages[0].run_id, pages } }];
"""
            )
        },
        (2200, 80),
    )
    f.add(
        "Process batch (A1)",
        "n8n-nodes-base.executeWorkflow",
        1.2,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": WF_A1, "mode": "id"},
            "mode": "once",
            "options": {"waitForSubWorkflow": True},
        },
        (2420, 80),
    )
    f.add(
        "Run summary",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
return [{ json: { run_id: $('Start run').first().json.run_id, started_at: $('Start run').first().json.started_at } }];
"""
            )
        },
        (2200, -200),
    )
    f.add(
        "Finish run",
        PG_T,
        2.5,
        pg_query(
            """
WITH crawled AS (
  SELECT DISTINCT source_url FROM crawl_runs
  WHERE run_id = $1::uuid AND status IN ('ok', 'unchanged')
), deactivated AS (
  -- Only for pages crawled OK this run: a product that vanished from a healthy page is gone.
  -- Pages that failed/blocked keep their products (a bad crawl never wipes data).
  UPDATE loan_products p SET is_active = false
  WHERE p.is_active AND p.source_url IN (SELECT source_url FROM crawled)
    AND p.last_seen_at < $2::timestamptz
  RETURNING p.product_id
), superseded AS (
  UPDATE matches m SET status = 'superseded', superseded_at = now()
  WHERE m.status = 'active' AND m.product_id IN (SELECT product_id FROM deactivated)
  RETURNING 1
)
SELECT $1::text AS run_id,
  (SELECT count(*) FROM crawl_runs WHERE run_id = $1::uuid) AS pages,
  (SELECT json_object_agg(status, n) FROM (SELECT status, count(*) AS n FROM crawl_runs
     WHERE run_id = $1::uuid GROUP BY status) s) AS pages_by_status,
  (SELECT count(*) FROM loan_products WHERE is_active) AS active_products,
  (SELECT count(*) FROM loan_products WHERE last_changed_at >= $2::timestamptz) AS products_new_or_changed,
  -- Workflow B re-matches every user against exactly these products (product mode).
  (SELECT coalesce(json_agg(product_id), '[]'::json) FROM loan_products
     WHERE is_active AND last_changed_at >= $2::timestamptz) AS product_ids,
  (SELECT count(*) FROM deactivated) AS products_deactivated,
  (SELECT count(*) FROM superseded) AS matches_superseded,
  (SELECT coalesce(sum(llm_input_tokens), 0) FROM crawl_runs WHERE run_id = $1::uuid) AS llm_input_tokens,
  (SELECT coalesce(sum(llm_output_tokens), 0) FROM crawl_runs WHERE run_id = $1::uuid) AS llm_output_tokens
""",
            "={{ [ $json.run_id, $json.started_at ] }}",
        ),
        (2420, -200),
        credentials=PG,
    )
    # Crawl health: a site redesign shows up as a drop in usable pages, not as a failed run.
    f.add(
        "Crawl health",
        PG_T,
        2.5,
        pg_query(
            sql_file("crawl_health.sql"), f"={{{{ [ $json.run_id, {CRAWL_DROP_ALERT_PCT} ] }}}}"
        ),
        (2640, 40),
        credentials=PG,
    )
    f.add("Crawl degraded?", IF_T, 2, if_true("={{ $json.should_alert }}"), (2860, 40))
    f.add(
        "Email crawl alert (SES)",
        "n8n-nodes-base.awsSes",
        1,
        {
            "authentication": "assumeRole",
            "resource": "email",
            "operation": "send",
            "isBodyHtml": True,
            "fromEmail": SES_FROM,
            "toAddresses": [TEST_ALIASES[0]],
            "subject": "Loan engine: crawl degraded",
            "body": "={{ '<p>Workflow A run ' + $json.run_id + ': ' + $json.summary + '.</p>"
            "<p>Products from failed pages are kept; check the source pages for a layout change.</p>' }}",
            "additionalFields": {},
        },
        (3080, 40),
        credentials=AWS,
        retryOnFail=True,
        maxTries=2,
        waitBetweenTries=2000,
        onError="continueRegularOutput",  # the row is stored in workflow_errors either way
    )
    f.add(
        "Products changed?", IF_T, 2, if_true("={{ $json.product_ids.length > 0 }}"), (2640, -200)
    )
    f.add(
        "Re-match changed products (B)",
        "n8n-nodes-base.executeWorkflow",
        1.2,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": WF_B, "mode": "id"},
            "mode": "once",
            "options": {"waitForSubWorkflow": True},
        },
        (2860, -280),
        # The crawl itself succeeded and is recorded; a matching failure is B's to report
        # (B marks its run failed, Workflow E alerts), it must not mark the crawl failed.
        onError="continueRegularOutput",
    )

    for a, b in [
        ("Finish run", "Products changed?"),
        ("Every day 06:00 IST", "Start run"),
        ("Run now (demo)", "Start run"),
        ("Start run", "Origins to check"),
        ("Origins to check", "Fetch robots.txt"),
        ("Fetch robots.txt", "Robots rules"),
        ("Robots rules", "Hub sources"),
        ("Hub sources", "Fetch hub pages"),
        ("Fetch hub pages", "Discover pages"),
        ("Discover pages", "robots.txt allows?"),
        ("Batch → one item", "Process batch (A1)"),
        ("Process batch (A1)", "Every 5 pages"),
        ("Run summary", "Finish run"),
    ]:
        f.link(a, b)
    f.link("robots.txt allows?", "Every 5 pages", out=0)
    f.link("robots.txt allows?", "Log robots-disallowed", out=1)
    f.link("Every 5 pages", "Run summary", out=0)  # done
    f.link("Every 5 pages", "Batch → one item", out=1)  # loop
    f.link("Products changed?", "Re-match changed products (B)", out=0)
    f.link("Finish run", "Crawl health")
    f.link("Crawl health", "Crawl degraded?")
    f.link("Crawl degraded?", "Email crawl alert (SES)", out=0)
    return f.build()


# ---------------------------------------------------------------- Workflow B1 (one matching run)


def workflow_b1() -> dict:
    f = Flow(
        WF_B1,
        "B1 · Match one run (Treasure Hunt)",
        "Stage 0 compile criteria (LLM, cached) → Stage 1+2 SQL classes → stats → pre-write proof → Stage 3 expand/score/diff → post-write proof.",
    )
    f.sticky(
        "## B1 · The Optimization Treasure Hunt\n**Stage 0** · Nova Pro compiles each product's free-text "
        "criteria ONCE into checkable rules (cached by text hash) → LLM cost scales with distinct criteria "
        "texts, not users.\n**Stage 1+2** · SQL equivalence classes: every threshold is a cut point, users "
        "with identical intervals form one class → decide class x product.\n**Stage 3** · expand to users, "
        "fit score, diff vs active matches (one transaction, advisory lock).\n**Proofs** · a naive per-user "
        "re-evaluation must give 0 mismatches twice: BEFORE Stage 3 writes (class decisions) and AFTER "
        "(stored matches). A failure stops the run.",
        (-40, -420),
        (620, 320),
    )
    f.add(
        "From B (run)",
        "n8n-nodes-base.executeWorkflowTrigger",
        1.1,
        {"inputSource": "passthrough"},
        (0, 0),
    )
    f.add(
        "Criteria to compile",
        PG_T,
        2.5,
        pg_query(
            """
SELECT DISTINCT encode(sha256(convert_to(p.other_criteria_text, 'UTF8')), 'hex') AS text_id,
       p.other_criteria_text AS text
FROM loan_products p
WHERE p.is_active AND p.other_criteria_text IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM criteria_rules r
                  WHERE r.prompt_version = $1
                    AND r.criteria_text_hash = encode(sha256(convert_to(p.other_criteria_text, 'UTF8')), 'hex'))
ORDER BY 1
""",
            f"={{{{ [ '{COMPILE_PROMPT_VERSION}' ] }}}}",
        ),
        (220, 0),
        credentials=PG,
        alwaysOutputData=True,
    )
    f.add(
        "Batches of 10 texts",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
// Cache misses only. 10 texts per Nova call; usually 0 after the first run.
const texts = $input.all().map((i) => i.json).filter((t) => t.text_id);
const batches = [];
for (let i = 0; i < texts.length; i += 10) batches.push({ texts: texts.slice(i, i + 10) });
return batches.length ? batches.map((b) => ({ json: b })) : [{ json: { texts: [] } }];
"""
            )
        },
        (440, 0),
    )
    f.add("Anything to compile?", IF_T, 2, if_true("={{ $json.texts.length > 0 }}"), (660, 0))
    f.add(
        "Build compile request",
        CODE_T,
        2,
        {
            "jsCode": js(
                "structured.js",
                "compile.js",
                entry=prompt_constants("compile_criteria_v1", COMPILE_PROMPT_VERSION)
                + """
return $input.all().map((i) => ({ json: { texts: i.json.texts, request: buildCompileRequest(i.json.texts, PROMPT) } }));
""",
            )
        },
        (880, -160),
    )
    f.add(
        "Nova Pro · compile",
        HTTP_T,
        4.2,
        {
            "method": "POST",
            "url": f"https://bedrock-runtime.{REGION}.amazonaws.com/model/amazon.nova-pro-v1:0/converse",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "awsAssumeRole",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json.request) }}",
            "options": {
                "timeout": 120000,
                "batching": {"batch": {"batchSize": 1, "batchInterval": 1000}},
            },
        },
        (1100, -160),
        credentials=AWS,
        retryOnFail=True,
        maxTries=3,
        waitBetweenTries=5000,
        onError="continueRegularOutput",
    )
    f.add(
        "Validate compiled rules",
        CODE_T,
        2,
        {
            "jsCode": js(
                "normalize.js",
                "structured.js",
                "compile.js",
                entry=f"""
// Every rule is re-checked against its source text; failures become requirements.
const PROMPT_VERSION = {json.dumps(COMPILE_PROMPT_VERSION)};
const rows = [];
let inTok = 0, outTok = 0, calls = 0;
$input.all().forEach((item, i) => {{
  const {{ texts }} = $('Build compile request').itemMatching(i).json;
  const res = item.json.error ? {{ message: item.json.error.message || 'request failed' }} : item.json;
  const parsed = parseCompileResponse(res, texts);
  calls += 1; inTok += parsed.inputTokens; outTok += parsed.outputTokens;
  for (const t of texts) {{
    const c = parsed.byId[t.text_id];
    if (c) rows.push({{ criteria_text_hash: t.text_id, prompt_version: PROMPT_VERSION, rules: c.rules,
                       requirements: c.requirements, model_id: 'amazon.nova-pro-v1:0' }});
    // Not compiled (LLM failed): no row, so the product stays "conditional" and is retried next run.
  }}
}});
const cost = (inTok / 1000) * {NOVA_PRO_USD_PER_1K["input"]} + (outTok / 1000) * {NOVA_PRO_USD_PER_1K["output"]};
return [{{ json: {{ rows, calls, inTok, outTok, cost }} }}];
""",
            )
        },
        (1320, -160),
    )
    f.add(
        "Save compiled rules",
        PG_T,
        2.5,
        pg_query(
            """
WITH ins AS (
  INSERT INTO criteria_rules (criteria_text_hash, prompt_version, rules, requirements, model_id,
                              llm_input_tokens, llm_output_tokens)
  SELECT criteria_text_hash, prompt_version, rules, requirements, model_id, NULL, NULL
  FROM jsonb_to_recordset($2::jsonb) AS r(criteria_text_hash text, prompt_version text, rules jsonb,
                                          requirements jsonb, model_id text)
  ON CONFLICT (criteria_text_hash, prompt_version) DO NOTHING
  RETURNING 1
)
UPDATE pipeline_runs SET rules_compiled = (SELECT count(*) FROM ins), llm_calls = $3::int,
       llm_input_tokens = $4::int, llm_output_tokens = $5::int, llm_cost_usd_est = $6::numeric
WHERE run_id = $1::uuid
RETURNING rules_compiled, llm_calls
""",
            "={{ [ $('From B (run)').first().json.run_id, JSON.stringify($json.rows), $json.calls, $json.inTok, $json.outTok, $json.cost ] }}",
        ),
        (1540, -160),
        credentials=PG,
    )
    f.add(
        "Stage 1+2 · classes & decisions",
        PG_T,
        2.5,
        pg_query(
            sql_file("stage1_classes.sql"),
            f"={{{{ [ $('From B (run)').first().json.run_id, '{COMPILE_PROMPT_VERSION}' ] }}}}",
        ),
        (1760, 0),
        credentials=PG,
    )
    f.add(
        "Refresh planner stats",
        PG_T,
        2.5,
        pg_query(sql_file("refresh_stats.sql")),
        (1980, 0),
        credentials=PG,
        alwaysOutputData=True,
    )
    # Pre-write proof: the class decisions, expanded to users, must equal a naive per-user
    # evaluation BEFORE Stage 3 writes a single match. On a mismatch the run stops here.
    f.add(
        "Pre-write proof",
        PG_T,
        2.5,
        pg_query(
            sql_file("prewrite_check.sql"),
            f"={{{{ [ $('From B (run)').first().json.run_id, '{COMPILE_PROMPT_VERSION}' ] }}}}",
        ),
        (2200, 0),
        credentials=PG,
    )
    f.add(
        "Pre-write passed?",
        IF_T,
        2,
        if_true("={{ $json.prewrite_ok === true && Number($json.mismatches) === 0 }}"),
        (2420, 0),
    )
    f.add(
        "Stop: pre-write proof failed",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const p = $input.first().json;
throw new Error(`Pre-write proof failed: ${p.mismatches} of ${p.pairs_checked} pairs differ from the naive check (${p.users_without_class} users without a class). No match was written.`);
"""
            )
        },
        (2640, 200),
    )
    f.add(
        "Stage 3 · expand, score, diff",
        PG_T,
        2.5,
        pg_query(sql_file("stage3_expand.sql"), "={{ [ $('From B (run)').first().json.run_id ] }}"),
        (2640, 0),
        credentials=PG,
    )
    f.add(
        "Correctness proof",
        PG_T,
        2.5,
        pg_query(
            sql_file("brute_force_check.sql"),
            f"={{{{ [ $('From B (run)').first().json.run_id, '{COMPILE_PROMPT_VERSION}' ] }}}}",
        ),
        (2860, 0),
        credentials=PG,
    )
    f.add(
        "Finish run",
        PG_T,
        2.5,
        pg_query(
            """
UPDATE pipeline_runs SET status = 'done', finished_at = now(),
       rules_compiled = coalesce(rules_compiled, 0), llm_calls = coalesce(llm_calls, 0),
       llm_cache_hits = residual_texts - coalesce(rules_compiled, 0),
       llm_input_tokens = coalesce(llm_input_tokens, 0), llm_output_tokens = coalesce(llm_output_tokens, 0),
       llm_cost_usd_est = coalesce(llm_cost_usd_est, 0)
WHERE run_id = $1::uuid
RETURNING run_id::text, mode, job_id::text, users_in, products_in, naive_pairs, classes,
          class_product_pairs, pairs_after_sql, rule_decided, llm_candidates, not_eligible_pairs,
          residual_texts, rules_compiled, llm_cache_hits, llm_calls, llm_input_tokens, llm_output_tokens,
          llm_cost_usd_est, matches_new, matches_superseded, matches_unchanged, prewrite_ok,
          correctness_ok
""",
            "={{ [ $('From B (run)').first().json.run_id ] }}",
        ),
        (3300, 0),
        credentials=PG,
    )
    # The proof GATES the run: if the class pipeline disagrees with checking every pair one by
    # one, nothing is marked done and nobody is emailed (B marks the job failed, E alerts).
    f.add(
        "Proof passed?",
        IF_T,
        2,
        if_true("={{ $json.correctness_ok === true && Number($json.mismatches) === 0 }}"),
        (3080, 0),
    )
    f.add(
        "Stop: proof failed",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const p = $input.first().json;
throw new Error(`Correctness proof failed: ${p.mismatches} of ${p.naive_pairs_evaluated} pairs differ from the brute-force check. Run stopped before notification.`);
"""
            )
        },
        (3300, 200),
    )
    f.add(
        "Treasure Hunt funnel",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
// One item that reads like the README table: how much work each stage removed, and the proof.
const r = $input.first().json;
const proof = $('Correctness proof').first().json;
const pre = $('Pre-write proof').first().json;
const ratio = (a, b) => (a && b ? Math.round((Number(b) / Number(a)) * 10000) / 100 : null);
return [{ json: {
  run_id: r.run_id, mode: r.mode, job_id: r.job_id,
  funnel: {
    naive_pairs: r.naive_pairs,
    pairs_passing_published_rules: r.pairs_after_sql,
    equivalence_classes: r.classes,
    class_product_decisions: r.class_product_pairs,
    decisions_as_share_of_naive_pct: ratio(r.naive_pairs, r.class_product_pairs),
    llm_calls: r.llm_calls, llm_cache_hits: r.llm_cache_hits, llm_cost_usd_est: r.llm_cost_usd_est,
    matches_new: r.matches_new, matches_superseded: r.matches_superseded, matches_unchanged: r.matches_unchanged,
  },
  proof: {
    before_write: { pairs_checked: pre.pairs_checked, mismatches: pre.mismatches, ok: pre.prewrite_ok },
    after_write: { pairs_checked: proof.naive_pairs_evaluated, mismatches: proof.mismatches, ok: proof.correctness_ok },
  },
} }];
"""
            )
        },
        (3520, 0),
    )

    for a, b in [
        ("From B (run)", "Criteria to compile"),
        ("Criteria to compile", "Batches of 10 texts"),
        ("Batches of 10 texts", "Anything to compile?"),
        ("Build compile request", "Nova Pro · compile"),
        ("Nova Pro · compile", "Validate compiled rules"),
        ("Validate compiled rules", "Save compiled rules"),
        ("Save compiled rules", "Stage 1+2 · classes & decisions"),
        ("Stage 1+2 · classes & decisions", "Refresh planner stats"),
        ("Refresh planner stats", "Pre-write proof"),
        ("Pre-write proof", "Pre-write passed?"),
        ("Stage 3 · expand, score, diff", "Correctness proof"),
        ("Correctness proof", "Proof passed?"),
        ("Finish run", "Treasure Hunt funnel"),
    ]:
        f.link(a, b)
    f.link("Pre-write passed?", "Stage 3 · expand, score, diff", out=0)
    f.link("Pre-write passed?", "Stop: pre-write proof failed", out=1)
    f.link("Proof passed?", "Finish run", out=0)
    f.link("Proof passed?", "Stop: proof failed", out=1)
    f.link("Anything to compile?", "Build compile request", out=0)
    f.link("Anything to compile?", "Stage 1+2 · classes & decisions", out=1)
    return f.build()


# ---------------------------------------------------------------- Workflow B (triggers + claim)


def workflow_b() -> dict:
    f = Flow(
        WF_B,
        "B · User-loan matching",
        "Triggered by the ingest webhook (primary), a 10-min sweeper (recovery), or Workflow A (product mode).",
    )
    f.sticky(
        "## B · User-loan matching\n**Triggers**\n- **Webhook** `POST /webhook/ingest-complete` (header "
        "secret, private network) right after a CSV is ingested.\n- **Sweeper** every 10 min: recovers jobs "
        "whose webhook was missed (n8n down, network blip), and runs that matched but never recorded their emails "
        "(proved again, then C finishes them).\n- **From A** (product mode): re-match all users "
        "against new/changed products.\n\n**Claim** = atomic lock on the job, so duplicates and concurrent "
        "triggers never double-match. Then **B1** runs the Treasure Hunt, **C** notifies, and products "
        "whose criteria compiled late are re-matched for every user (product mode, never loops).",
        (-40, -440),
        (600, 340),
    )
    # First trigger in the file = the one `n8n execute` (CLI) starts from.
    f.add("Run now (demo)", "n8n-nodes-base.manualTrigger", 1, {}, (0, 200))
    f.add(
        "Ingest complete (webhook)",
        "n8n-nodes-base.webhook",
        2,
        {
            "httpMethod": "POST",
            "path": "ingest-complete",
            "authentication": "headerAuth",
            "responseMode": "onReceived",
            "options": {},
        },
        (0, -120),
        credentials=WEBHOOK_AUTH,
        webhookId="6f1c0b2e-6b53-4c1e-9a7d-6f3c2a1b0e01",
    )
    f.add(
        "Sweeper every 10 min",
        "n8n-nodes-base.scheduleTrigger",
        1.2,
        {"rule": {"interval": [{"field": "minutes", "minutesInterval": 10}]}},
        (0, 60),
    )
    f.add(
        "From A (product mode)",
        "n8n-nodes-base.executeWorkflowTrigger",
        1.1,
        {"inputSource": "passthrough"},
        (0, 360),
    )
    f.add(
        "Webhook → request",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
// The header secret proves WHO called; still validate WHAT they sent before it reaches SQL.
const body = $input.first().json.body || {};
const jobId = String(body.job_id || '').trim().toLowerCase();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
return UUID.test(jobId) ? [{ json: { mode: 'upload', job_id: jobId, product_ids: '' } }] : [];
"""
            )
        },
        (220, -120),
    )
    f.add(
        "Jobs waiting for matching",
        PG_T,
        2.5,
        pg_query(sql_file("sweeper.sql")),
        (220, 130),
        credentials=PG,
    )
    f.add(
        "Products → request",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const ids = $input.first().json.product_ids || [];
return ids.length ? [{ json: { mode: 'products', job_id: '', product_ids: JSON.stringify(ids) } }] : [];
"""
            )
        },
        (220, 360),
    )
    f.add(
        "Claim job + start run",
        PG_T,
        2.5,
        pg_query(
            sql_file("claim.sql"),
            "={{ [ $json.mode, $json.job_id, $json.product_ids ] }}",
        ),
        (440, 120),
        credentials=PG,
    )
    f.add(
        "Match (B1)",
        "n8n-nodes-base.executeWorkflow",
        1.2,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": WF_B1, "mode": "id"},
            "mode": "each",
            "options": {"waitForSubWorkflow": True},
        },
        (660, 120),
        onError="continueRegularOutput",
    )
    f.add("Matching failed?", IF_T, 2, if_true("={{ !!$json.error }}"), (880, 120))
    f.add(
        "Mark job failed",
        PG_T,
        2.5,
        pg_query(
            """
WITH run AS (
  UPDATE pipeline_runs SET status = 'failed', finished_at = now(), error = left($2, 2000)
  WHERE run_id = $1::uuid RETURNING job_id
)
UPDATE upload_jobs SET match_status = 'FAILED'
WHERE job_id = (SELECT job_id FROM run)
RETURNING job_id::text
""",
            "={{ [ $('Claim job + start run').itemMatching($itemIndex).json.run_id, JSON.stringify($json.error) ] }}",
        ),
        (1100, 220),
        credentials=PG,
    )
    f.add(
        "Notify users (C)",
        "n8n-nodes-base.executeWorkflow",
        1.2,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": WF_C, "mode": "id"},
            "mode": "each",
            "options": {"waitForSubWorkflow": True},
        },
        (1100, 20),
        onError="continueRegularOutput",
    )

    for a, b in [
        ("Ingest complete (webhook)", "Webhook → request"),
        ("Webhook → request", "Claim job + start run"),
        ("Sweeper every 10 min", "Jobs waiting for matching"),
        ("Run now (demo)", "Jobs waiting for matching"),
        ("Jobs waiting for matching", "Claim job + start run"),
        ("From A (product mode)", "Products → request"),
        ("Products → request", "Claim job + start run"),
        ("Claim job + start run", "Match (B1)"),
        ("Match (B1)", "Matching failed?"),
    ]:
        f.link(a, b)
    f.link("Matching failed?", "Mark job failed", out=0)
    f.link("Matching failed?", "Notify users (C)", out=1)
    # Second sweeper task: runs that wrote matches but never recorded emails (n8n lost its
    # database or restarted between Stage 3 and C). Prove again, then let C finish: C is
    # idempotent, so nobody is emailed twice.
    f.add(
        "Runs waiting for emails",
        PG_T,
        2.5,
        pg_query(sql_file("notify_recovery.sql")),
        (220, -200),
        credentials=PG,
    )
    f.add(
        "Prove again before emailing",
        PG_T,
        2.5,
        pg_query(
            sql_file("brute_force_check.sql"),
            f"={{{{ [ $json.run_id, '{COMPILE_PROMPT_VERSION}' ] }}}}",
        ),
        (440, -200),
        credentials=PG,
    )
    f.add(
        "Proof still passes?",
        IF_T,
        2,
        if_true("={{ $json.correctness_ok === true && Number($json.mismatches) === 0 }}"),
        (660, -200),
    )
    f.add(
        "Mark run recovered",
        PG_T,
        2.5,
        pg_query(sql_file("mark_run_recovered.sql"), "={{ [ $json.run_id ] }}"),
        (880, -200),
        credentials=PG,
    )
    f.add(
        "Finish emails (C)",
        "n8n-nodes-base.executeWorkflow",
        1.2,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": WF_C, "mode": "id"},
            "mode": "each",
            "options": {"waitForSubWorkflow": True},
        },
        (1100, -200),
        onError="continueRegularOutput",
    )
    f.link("Sweeper every 10 min", "Runs waiting for emails")
    f.link("Runs waiting for emails", "Prove again before emailing")
    f.link("Prove again before emailing", "Proof still passes?")
    f.link("Proof still passes?", "Mark run recovered", out=0)
    f.link("Mark run recovered", "Finish emails (C)")
    if REMATCH_LATE_COMPILES:
        f.add(
            "Products compiled late",
            PG_T,
            2.5,
            pg_query(
                sql_file("products_compiled_late.sql"),
                f"={{{{ [ $('Claim job + start run').itemMatching($itemIndex).json.run_id, "
                f"'{COMPILE_PROMPT_VERSION}' ] }}}}",
            ),
            (1100, 400),
            credentials=PG,
        )
        f.add(
            "Re-match them?", IF_T, 2, if_true("={{ $json.product_ids.length > 0 }}"), (1320, 400)
        )
        # Fire and forget: the product-mode run is its own execution (no nesting B -> B -> ...).
        f.add(
            "Re-match all users (B, product mode)",
            "n8n-nodes-base.executeWorkflow",
            1.2,
            {
                "source": "database",
                "workflowId": {"__rl": True, "value": WF_B, "mode": "id"},
                "mode": "once",
                "options": {"waitForSubWorkflow": False},
            },
            (1540, 400),
        )
        # From the success branch itself, not after C: C returns nothing when no one has new
        # matches, and late compiles still need their re-match then.
        f.link("Matching failed?", "Products compiled late", out=1)
        f.link("Products compiled late", "Re-match them?")
        f.link("Re-match them?", "Re-match all users (B, product mode)", out=0)
    return f.build()


# ---------------------------------------------------------------- Workflow C (notify)


def workflow_c(api_url: str) -> dict:
    f = Flow(
        WF_C,
        "C · Notify matched users (SES)",
        "One personalized email per user with new matches: best pick + top picks, sent via the AWS SES node.",
    )
    f.sticky(
        "## C · User notification\nRuns after **B**. For each user with NEW matches: one email with the "
        "**best pick + top picks** (top 5, one per lender, best platform shown), why each fits, and what else "
        "they'd need.\n\n- Sent with the **AWS SES node** (Assume Role credential, no keys), 1 email/second "
        "(SES sandbox).\n- **Only to test aliases**: never the CSV address (guarded in code).\n- Demo cap: "
        f"first {DEMO_MAX_EMAILS} users get real mail; every other user's email is still **composed and "
        "stored** by **C1** (batches of 500), recorded as `skipped_demo`.\n- Each send "
        "is **recorded the moment SES answers**, so a crash mid-loop never emails anyone twice.",
        (-40, -400),
        (620, 300),
    )
    f.add("Run now (latest run)", "n8n-nodes-base.manualTrigger", 1, {}, (0, -80))
    f.add(
        "Latest run with new matches",
        PG_T,
        2.5,
        pg_query("""
SELECT run_id::text FROM pipeline_runs
WHERE status = 'done' AND matches_new > 0
ORDER BY finished_at DESC LIMIT 1
"""),
        (220, -80),
        credentials=PG,
    )
    f.add(
        "From B (run)",
        "n8n-nodes-base.executeWorkflowTrigger",
        1.1,
        {"inputSource": "passthrough"},
        (0, 100),
    )
    # The run, in one place: every later node reads it from here, so C still knows its run when
    # there is nobody left to email (and can record that).
    f.add(
        "Run to notify",
        CODE_T,
        2,
        {"jsCode": js(entry="return [{ json: { run_id: $input.first().json.run_id } }];")},
        (330, 0),
    )
    f.add(
        "Users to email",
        PG_T,
        2.5,
        pg_query(
            sql_file("notify_users.sql"),
            f"={{{{ [ $('Run to notify').first().json.run_id, {DEMO_MAX_EMAILS} ] }}}}",
        ),
        (440, 0),
        credentials=PG,
        alwaysOutputData=True,  # nobody to email still continues to the finish step
    )
    f.add(
        "Anyone to email?",
        IF_T,
        2,
        if_true("={{ !!$('Users to email').first().json.user_id }}"),
        (500, 120),
    )
    # ONE call per run: the api Lambda signs a 14-day dashboard link per user. The HMAC key
    # stays in AWS; n8n authenticates with the same Header Auth credential as the webhook.
    f.add(
        "Sign dashboard links",
        HTTP_T,
        4.2,
        {
            "method": "POST",
            "url": f"{api_url}/internal/email-tokens",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ user_ids: $('Users to email').all().map((i) => i.json.user_id) }) }}",
            "options": {"timeout": 10000},
        },
        (550, 0),
        credentials=WEBHOOK_AUTH,
        executeOnce=True,
        retryOnFail=True,
        maxTries=2,
        waitBetweenTries=1000,
        # No link is better than no email: on failure the emails go out without it.
        onError="continueRegularOutput",
    )
    f.add(
        "Compose emails",
        CODE_T,
        2,
        {
            "jsCode": js(
                "email.js",
                entry=f"""
const ALIASES = {json.dumps(TEST_ALIASES)};
const FROM = {json.dumps(SES_FROM)};
const APP = {json.dumps(api_url + "/app/dashboard?t=")};
const tokens = $('Sign dashboard links').first()?.json?.tokens || {{}};
return $('Users to email').all().map((item) => {{
  const user = item.json;
  // Guard: the recipient is one of OUR test aliases, chosen deterministically; never the CSV email.
  const to = assertAllowed(recipientFor(user.user_id, ALIASES), ALIASES);
  const token = tokens[user.user_id];
  const dashboard_url = token ? APP + encodeURIComponent(token) : null;
  return {{ json: {{ user_id: user.user_id, to, from: FROM, ...composeEmail({{ ...user, dashboard_url }}) }} }};
}});
""",
            )
        },
        (770, 0),
    )
    f.add(
        "One email at a time",
        "n8n-nodes-base.splitInBatches",
        3,
        {"batchSize": 1, "options": {}},
        (880, 0),
    )
    f.add(
        "Send via AWS SES",
        "n8n-nodes-base.awsSes",
        1,
        {
            "authentication": "assumeRole",
            "resource": "email",
            "operation": "send",
            "isBodyHtml": True,
            "fromEmail": "={{ $json.from }}",
            "toAddresses": ["={{ $json.to }}"],
            "subject": "={{ $json.subject }}",
            "body": "={{ $json.html }}",
            "additionalFields": {},
        },
        (1100, 100),
        credentials=AWS,
        retryOnFail=True,
        maxTries=2,
        waitBetweenTries=2000,
        onError="continueRegularOutput",
    )
    f.add(
        "Delivery result",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
const email = $('One email at a time').first().json;
const r = $input.first().json;
const id = r.MessageId || r.messageId || r?.SendEmailResponse?.SendEmailResult?.MessageId || null;
return [{ json: { user_id: email.user_id, alias_email: email.to, status: r.error || !id ? 'failed' : 'sent',
  ses_message_id: id, error: r.error ? String(r.error.message || JSON.stringify(r.error)).slice(0, 500) : (id ? null : 'no MessageId'),
  subject: email.subject, text: email.text } }];
"""
            )
        },
        (1320, 100),
    )
    # Recorded the moment SES answers: a crash mid-loop never emails anyone twice. Returns the
    # same fields as "Delivery result", so the loop's done output is unchanged.
    f.add(
        "Record this send",
        PG_T,
        2.5,
        pg_query(
            sql_file("notify_record_send.sql"),
            "={{ [ JSON.stringify({ run_id: $('Run to notify').first().json.run_id, "
            "user_id: $json.user_id, alias_email: $json.alias_email, status: $json.status, "
            "ses_message_id: $json.ses_message_id || '', error: $json.error || '', "
            "subject: $json.subject || '', body_text: $json.text || '' }) ] }}",
        ),
        (1540, 100),
        credentials=PG,
    )
    f.add(
        "1 email / second (SES sandbox)",
        "n8n-nodes-base.wait",
        1.1,
        {"resume": "timeInterval", "amount": 1.1, "unit": "seconds"},
        (1760, 100),
    )
    # The loop's "done" output carries one item per email; a Postgres node runs once PER ITEM,
    # so collapse to ONE item first (found live: the summary query ran 5x and duplicated rows).
    f.add(
        "All results -> one item",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
// Sends were recorded one by one; the summary only needs the run.
return [{ json: { run_id: $('Run to notify').first().json.run_id, results: $input.all().length } }];
"""
            )
        },
        (1100, -120),
    )
    f.add(
        "Record notifications",
        PG_T,
        2.5,
        pg_query(sql_file("notify_finish.sql"), "={{ [ $json.run_id ] }}"),
        (1100, -120),
        credentials=PG,
    )

    for a, b in [
        ("Run now (latest run)", "Latest run with new matches"),
        ("Latest run with new matches", "Run to notify"),
        ("From B (run)", "Run to notify"),
        ("Run to notify", "Users to email"),
        ("Users to email", "Anyone to email?"),
        ("Sign dashboard links", "Compose emails"),
        ("Compose emails", "One email at a time"),
        ("Send via AWS SES", "Delivery result"),
        ("Delivery result", "Record this send"),
        ("Record this send", "1 email / second (SES sandbox)"),
        ("1 email / second (SES sandbox)", "One email at a time"),
    ]:
        f.link(a, b)
    # Every other matched user's email is composed too (C1, 500 per execution, so a 10k run
    # never holds all emails in one execution); only delivery is capped by the SES sandbox.
    f.add(
        "Compose the rest (C1)",
        "n8n-nodes-base.executeWorkflow",
        1.2,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": WF_C1, "mode": "id"},
            "mode": "once",
            "options": {"waitForSubWorkflow": True},
        },
        (1320, -120),
    )
    f.add(
        "More to compose?",
        IF_T,
        2,
        # Ends when nothing remains, when a batch stored nothing, or after 200 batches (100k
        # users): the loop can never spin forever.
        if_true(
            "={{ Number($json.remaining) > 0 && Number($json.composed) > 0 && $runIndex < 200 }}"
        ),
        (1540, -120),
    )
    f.link("Anyone to email?", "Sign dashboard links", out=0)
    # Nobody to email (all sent already, e.g. a re-run after a crash): go straight to the finish
    # step, which records the skipped users and the run's counters.
    f.link("Anyone to email?", "All results -> one item", out=1)
    f.link("One email at a time", "All results -> one item", out=0)  # done
    f.link("All results -> one item", "Record notifications")
    f.link("Record notifications", "Compose the rest (C1)")
    f.link("Compose the rest (C1)", "More to compose?")
    f.link("More to compose?", "Compose the rest (C1)", out=0)
    f.link("One email at a time", "Send via AWS SES", out=1)  # loop
    return f.build()


# ---------------------------------------------------------------- Workflow C1 (compose batch)


def workflow_c1() -> dict:
    f = Flow(
        WF_C1,
        "C1 · Compose a batch of emails (sub-workflow)",
        f"Builds and stores the personalized email of up to {COMPOSE_BATCH} users whose send was skipped by the demo cap.",
    )
    f.sticky(
        f"## C1 · Compose a batch (≤{COMPOSE_BATCH} users)\nCalled by **C** in a loop after the real sends. "
        "Every matched user gets their personalized email **built and stored** (subject + text on their "
        "notification row); only delivery is capped by the SES sandbox.\n\n- One execution per batch, "
        "so memory stays bounded on a 10,000-user run.\n- Never sends anything: no SES node here.",
        (-40, -340),
        (560, 260),
    )
    f.add(
        "From C (run)",
        "n8n-nodes-base.executeWorkflowTrigger",
        1.1,
        {"inputSource": "passthrough"},
        (0, 0),
    )
    f.add(
        "Next users to compose",
        PG_T,
        2.5,
        pg_query(
            sql_file("notify_compose_batch.sql"),
            f"={{{{ [ $json.run_id, {COMPOSE_BATCH} ] }}}}",
        ),
        (220, 0),
        credentials=PG,
    )
    f.add(
        "Compose (no send)",
        CODE_T,
        2,
        {
            "jsCode": js(
                "email.js",
                entry="""
const users = $input.all().map((i) => i.json);
return [{ json: { run_id: users[0].run_id, emails: composeBatch(users) } }];
""",
            )
        },
        (440, 0),
    )
    f.add(
        "Save composed emails",
        PG_T,
        2.5,
        pg_query(
            sql_file("notify_save_composed.sql"),
            "={{ [ $json.run_id, JSON.stringify($json.emails) ] }}",
        ),
        (660, 0),
        credentials=PG,
    )
    for a, b in [
        ("From C (run)", "Next users to compose"),
        ("Next users to compose", "Compose (no send)"),
        ("Compose (no send)", "Save composed emails"),
    ]:
        f.link(a, b)
    return f.build()


# ---------------------------------------------------------------- Workflow E (errors)


def workflow_e() -> dict:
    f = Flow(
        WF_E,
        "E · Error handler",
        "Error workflow of A, A1, B, B1 and C: records every failure in workflow_errors and emails an alert.",
        error_workflow=None,
    )
    f.sticky(
        "## E · Error handler\nSet as the **error workflow** of A, A1, B, B1 and C: any failed production "
        "execution (schedule, webhook, sub-workflow) lands here.\n\n- Every failure is stored in "
        "`workflow_errors` (workflow, node, message, execution id).\n- One **alert email** to the test "
        "alias, at most once per workflow every 30 min (a failing schedule must not drain the SES quota)."
        "\n- **Drill**: the manual trigger replays a sample error to prove the path end to end.",
        (-40, -420),
        (620, 300),
    )
    # First trigger in the file = the one `n8n execute` (CLI) starts from: the drill.
    f.add("Drill: simulate an error", "n8n-nodes-base.manualTrigger", 1, {}, (0, 160))
    f.add(
        "Sample error payload",
        CODE_T,
        2,
        {
            "jsCode": js(
                entry="""
// Same shape n8n's Error Trigger emits for a failed execution.
return [{ json: {
  execution: { id: 'drill-' + Date.now(), mode: 'drill', lastNodeExecuted: 'Claim job + start run',
               error: { message: 'Drill: simulated failure to test the error path end to end' } },
  workflow: { id: 'drill', name: 'E · drill (simulated)' },
} }];
"""
            )
        },
        (220, 160),
    )
    f.add("On workflow error", "n8n-nodes-base.errorTrigger", 1, {}, (0, -40))
    f.add(
        "Summarize error",
        CODE_T,
        2,
        {
            "jsCode": js(
                "errors.js",
                entry="""
const rec = summarizeError($input.first().json);
return [{ json: { ...rec, ...composeAlert(rec) } }];
""",
            )
        },
        (440, 40),
    )
    f.add(
        "Record error",
        PG_T,
        2.5,
        pg_query(
            """
-- Store the failure; alert only if this workflow had no error in the last
-- 30 minutes (prev is read from the snapshot BEFORE this insert).
-- One JSON parameter: error messages can hold newlines, which n8n's plain query
-- parameters do not survive (found live in Workflow C).
WITH e AS (
  SELECT * FROM jsonb_to_record($1::jsonb)
         AS r(workflow text, node text, message text, execution_id text)
), prev AS (
  SELECT max(created_at) AS last_at FROM workflow_errors
  WHERE workflow = (SELECT workflow FROM e)
), ins AS (
  INSERT INTO workflow_errors (workflow, node, message, execution_id)
  SELECT workflow, nullif(node, ''), message, nullif(execution_id, '') FROM e
  RETURNING id
)
SELECT (SELECT id FROM ins) AS error_id,
       coalesce((SELECT last_at FROM prev) < now() - interval '30 minutes', true) AS should_alert
""",
            "={{ [ JSON.stringify({ workflow: $json.workflow, node: $json.node || '', "
            "message: $json.message, execution_id: String($json.execution_id || '') }) ] }}",
        ),
        (660, 40),
        credentials=PG,
        retryOnFail=True,
        maxTries=3,
        waitBetweenTries=3000,
    )
    f.add("Alert due?", IF_T, 2, if_true("={{ $json.should_alert }}"), (880, 40))
    f.add(
        "Email alert (SES)",
        "n8n-nodes-base.awsSes",
        1,
        {
            "authentication": "assumeRole",
            "resource": "email",
            "operation": "send",
            "isBodyHtml": True,
            "fromEmail": SES_FROM,
            "toAddresses": [TEST_ALIASES[0]],
            "subject": "={{ $('Summarize error').first().json.subject }}",
            "body": "={{ $('Summarize error').first().json.html }}",
            "additionalFields": {},
        },
        (1100, 0),
        credentials=AWS,
        retryOnFail=True,
        maxTries=2,
        waitBetweenTries=2000,
        # The row is already stored: a failed alert must not fail the error handler itself.
        onError="continueRegularOutput",
    )
    for a, b in [
        ("Drill: simulate an error", "Sample error payload"),
        ("Sample error payload", "Summarize error"),
        ("On workflow error", "Summarize error"),
        ("Summarize error", "Record error"),
        ("Record error", "Alert due?"),
    ]:
        f.link(a, b)
    f.link("Alert due?", "Email alert (SES)", out=0)
    return f.build()


def workflow_e1() -> dict:
    f = Flow(
        WF_E1,
        "E1 · Error drill (fails on purpose)",
        "Fails on purpose so the real error path (Error Trigger -> workflow_errors -> alert) can be shown.",
    )
    f.sticky(
        "## E1 · Error drill\n`scripts/n8n-workflows.sh drill` publishes it for one scheduled run; it **fails on purpose**. Because its error workflow is **E**, n8n "
        "starts E with the real failure payload -> a `workflow_errors` row + an alert email. Proves the "
        "same path every production workflow (A, A1, B, B1, C) uses.",
        (-40, -320),
        (520, 220),
    )
    # A schedule, not a manual run: error workflows fire for production executions inside the
    # n8n server. `scripts/n8n-workflows.sh drill` publishes E1, waits for ONE scheduled
    # failure, then unpublishes it (it is never left running).
    f.add(
        "Run drill",
        "n8n-nodes-base.scheduleTrigger",
        1.2,
        {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}},
        (0, 0),
    )
    f.add(
        "Fail on purpose",
        CODE_T,
        2,
        {
            "jsCode": "throw new Error('E1 drill: deliberate failure to prove the error workflow');\n"
        },
        (220, 0),
    )
    f.link("Run drill", "Fail on purpose")
    return f.build()


def main() -> None:
    # The page hash embeds NORMALIZER_VERSION: the JS constant and ours must agree.
    js_version = (
        (CODE / "normalize.js").read_text().split("const NORMALIZER_VERSION = ")[1].split(";")[0]
    )
    if int(js_version) != NORMALIZER_VERSION:
        raise SystemExit(
            f"NORMALIZER_VERSION mismatch: normalize.js={js_version}, generator={NORMALIZER_VERSION}"
        )
    OUT.mkdir(parents=True, exist_ok=True)
    # DATA_BUCKET lets CI regenerate the workflows without AWS access (not a secret: the
    # bucket name is already in the committed JSON). Locally it comes from the stack.
    bucket = os.environ.get("DATA_BUCKET") or stack_output("DataBucketName")
    # The public API base (signed dashboard links in Workflow C's emails). Not a secret.
    api_url = (os.environ.get("API_URL") or stack_output("HttpApiUrl")).rstrip("/")
    for filename, wf in (
        ("A_loan_discovery.json", workflow_a()),
        ("A1_process_batch.json", workflow_a1(bucket)),
        ("B_matching.json", workflow_b()),
        ("B1_match_run.json", workflow_b1()),
        ("C_notification.json", workflow_c(api_url)),
        ("C1_compose_batch.json", workflow_c1()),
        ("E_error_handler.json", workflow_e()),
        ("E1_error_drill.json", workflow_e1()),
    ):
        (OUT / filename).write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote n8n/workflows/{filename}: {len(wf['nodes'])} nodes")


if __name__ == "__main__":
    main()
