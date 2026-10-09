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
NORMALIZER_VERSION = 2  # keep equal to NORMALIZER_VERSION in n8n/code/normalize.js
# Part of every page hash: bumping the prompt or the normalizer re-processes each page once.
HASH_SALT = f"prompt={PROMPT_VERSION};normalizer={NORMALIZER_VERSION}"

WF_A = "LoanEngineWfA001"
WF_A1 = "LoanEngineWfA101"
WF_B = "LoanEngineWfB001"
WF_B1 = "LoanEngineWfB101"
WF_C = "LoanEngineWfC001"
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
COMPILE_PROMPT_VERSION = "compile_v1"
# Bedrock list price used for the cost ESTIMATE in pipeline_runs (USD per 1k tokens).
NOVA_PRO_USD_PER_1K = {"input": 0.0008, "output": 0.0032}
REGION = "ap-southeast-2"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 LoanEligibilityEngine-assignment/1.0"
)
# Credential ids as created in the n8n UI (README §5). Ids, not secrets.
PG = {"postgres": {"id": "PkRN0GO4XtFXA9pL", "name": "RDS app (n8n_workflows)"}}
AWS = {"awsAssumeRole": {"id": "fa286DA3YraErW57", "name": "AWS n8n role (assume)"}}
WEBHOOK_AUTH = {"httpHeaderAuth": {"id": "qaXP0OsyRtnbitga", "name": "Ingest webhook secret"}}


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
        "5. Finish: deactivate products that vanished from pages crawled OK; report.",
        (-40, -380),
        (560, 300),
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
    return f.build()


# ---------------------------------------------------------------- Workflow B1 (one matching run)


def workflow_b1() -> dict:
    f = Flow(
        WF_B1,
        "B1 · Match one run (Treasure Hunt)",
        "Stage 0 compile criteria (LLM, cached) → Stage 1+2 SQL classes → stats → Stage 3 expand/score/diff → proof.",
    )
    f.sticky(
        "## B1 · The Optimization Treasure Hunt\n**Stage 0** · Nova Pro compiles each product's free-text "
        "criteria ONCE into checkable rules (cached by text hash) → LLM cost scales with distinct criteria "
        "texts, not users.\n**Stage 1+2** · SQL equivalence classes: every threshold is a cut point, users "
        "with identical intervals form one class → decide class x product.\n**Stage 3** · expand to users, "
        "fit score, diff vs active matches (one transaction, advisory lock).\n**Proof** · naive per-user "
        "re-evaluation must give 0 mismatches.",
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
    f.add(
        "Stage 3 · expand, score, diff",
        PG_T,
        2.5,
        pg_query(sql_file("stage3_expand.sql"), "={{ [ $('From B (run)').first().json.run_id ] }}"),
        (2200, 0),
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
        (2420, 0),
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
          llm_cost_usd_est, matches_new, matches_superseded, matches_unchanged, correctness_ok
""",
            "={{ [ $('From B (run)').first().json.run_id ] }}",
        ),
        (2640, 0),
        credentials=PG,
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
        ("Refresh planner stats", "Stage 3 · expand, score, diff"),
        ("Stage 3 · expand, score, diff", "Correctness proof"),
        ("Correctness proof", "Finish run"),
    ]:
        f.link(a, b)
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
        "whose webhook was missed (n8n down, network blip).\n- **From A** (product mode): re-match all users "
        "against new/changed products.\n\n**Claim** = atomic lock on the job, so duplicates and concurrent "
        "triggers never double-match. Then **B1** runs the Treasure Hunt.",
        (-40, -440),
        (600, 320),
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
        pg_query("""
-- Janitor first: a run still 'running' after 30 min is dead (n8n's hard timeout is 10 min),
-- e.g. n8n restarted mid-run. Close it so the funnel table never shows ghost runs.
WITH dead AS (
  UPDATE pipeline_runs SET status = 'failed', finished_at = now(),
         error = 'abandoned: still running after 30 min (n8n restart or timeout)'
  WHERE status = 'running' AND started_at < now() - interval '30 minutes'
  RETURNING 1
)
-- Completed uploads never matched, or whose matching run died (> 15 min old lock).
SELECT 'upload' AS mode, job_id::text AS job_id, '' AS product_ids
FROM upload_jobs
WHERE status = 'COMPLETED'
  AND (match_status IS NULL OR (match_status = 'RUNNING' AND match_started_at < now() - interval '15 minutes'))
ORDER BY completed_at
LIMIT 5
"""),
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
            """
-- Atomic claim: only ONE run per job, even with a duplicate webhook + the sweeper racing.
-- 0 rows returned = nothing to do (already matched / running / unknown job) -> stop here.
WITH req AS (
  SELECT $1::text AS mode, nullif($2, '')::uuid AS job_id, nullif($3, '')::jsonb AS product_ids
), locked AS (
  UPDATE upload_jobs j SET match_status = 'RUNNING', match_started_at = now()
  FROM req
  WHERE req.mode = 'upload' AND j.job_id = req.job_id AND j.status = 'COMPLETED'
    AND (j.match_status IS NULL OR (j.match_status = 'RUNNING' AND j.match_started_at < now() - interval '15 minutes'))
  RETURNING j.job_id
), abandoned AS (  -- a re-claimed job's previous run died: close it (data-modifying CTEs always run)
  UPDATE pipeline_runs SET status = 'failed', finished_at = now(),
         error = 'abandoned: job re-claimed after a stale lock'
  WHERE status = 'running' AND job_id = (SELECT job_id FROM locked)
  RETURNING 1
)
INSERT INTO pipeline_runs (mode, job_id, scope_product_ids)
SELECT req.mode, (SELECT job_id FROM locked),
       CASE WHEN req.mode = 'products'
            THEN ARRAY(SELECT jsonb_array_elements_text(req.product_ids))::uuid[] END
FROM req
WHERE req.mode = 'products' OR EXISTS (SELECT 1 FROM locked)
RETURNING run_id::text, mode, job_id::text
""",
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
    return f.build()


# ---------------------------------------------------------------- Workflow C (notify)


def workflow_c() -> dict:
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
        f"first {DEMO_MAX_EMAILS} users get real mail; the rest are recorded as `skipped_demo`.",
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
    f.add(
        "Users to email",
        PG_T,
        2.5,
        pg_query(
            """
-- New, un-notified active matches of this run. The demo-capped first N users get their
-- top picks: best offer PER LENDER (best platform), ranked by tier, fit score, rate.
WITH new_m AS (
  SELECT m.user_id, m.tier, m.requirements, m.fit_score, m.fit_reasons,
         p.lender, p.lender_key, p.channel, p.product_url, p.product_name,
         p.interest_rate_min, p.interest_rate_max, p.loan_amount_max
  FROM matches m JOIN loan_products p USING (product_id)
  WHERE m.match_run_id = $1::uuid AND m.status = 'active' AND m.notified_at IS NULL
), per_user AS (
  SELECT user_id, count(*)::int AS matches_total, count(DISTINCT lender_key)::int AS lenders_total
  FROM new_m GROUP BY user_id
), chosen AS (
  SELECT user_id FROM per_user ORDER BY user_id LIMIT $2::int
), best_per_lender AS (
  SELECT DISTINCT ON (n.user_id, n.lender_key) n.*
  FROM new_m n JOIN chosen USING (user_id)
  ORDER BY n.user_id, n.lender_key, (n.tier = 'eligible') DESC, n.fit_score DESC,
           n.interest_rate_min NULLS LAST, n.product_name
), ranked AS (
  SELECT b.*, row_number() OVER (PARTITION BY b.user_id ORDER BY (b.tier = 'eligible') DESC,
         b.fit_score DESC, b.interest_rate_min NULLS LAST, b.product_name) AS rnk
  FROM best_per_lender b
)
SELECT $1::text AS run_id, u.user_id::text, u.name, u.monthly_income, u.credit_score, u.employment_status, u.age,
       pu.matches_total, pu.lenders_total,
       json_agg(json_build_object(
         'lender', r.lender, 'channel', r.channel, 'tier', r.tier, 'requirements', r.requirements,
         'interest_rate_min', r.interest_rate_min, 'interest_rate_max', r.interest_rate_max,
         'loan_amount_max', r.loan_amount_max, 'product_url', r.product_url,
         'fit_score', r.fit_score, 'fit_reasons', r.fit_reasons) ORDER BY r.rnk)
         FILTER (WHERE r.rnk <= 5) AS picks
FROM ranked r JOIN users u USING (user_id) JOIN per_user pu USING (user_id)
GROUP BY u.user_id, pu.matches_total, pu.lenders_total
ORDER BY u.user_id
""",
            f"={{{{ [ $json.run_id, {DEMO_MAX_EMAILS} ] }}}}",
        ),
        (440, 0),
        credentials=PG,
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
return $input.all().map((item) => {{
  const user = item.json;
  // Guard: the recipient is one of OUR test aliases, chosen deterministically; never the CSV email.
  const to = assertAllowed(recipientFor(user.user_id, ALIASES), ALIASES);
  return {{ json: {{ user_id: user.user_id, to, from: FROM, ...composeEmail(user) }} }};
}});
""",
            )
        },
        (660, 0),
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
  ses_message_id: id, error: r.error ? String(r.error.message || JSON.stringify(r.error)).slice(0, 500) : (id ? null : 'no MessageId') } }];
"""
            )
        },
        (1320, 100),
    )
    f.add(
        "1 email / second (SES sandbox)",
        "n8n-nodes-base.wait",
        1.1,
        {"resume": "timeInterval", "amount": 1.1, "unit": "seconds"},
        (1540, 100),
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
return [{ json: { run_id: $('Users to email').first().json.run_id, results: $input.all().map((i) => i.json) } }];
"""
            )
        },
        (1100, -120),
    )
    f.add(
        "Record notifications",
        PG_T,
        2.5,
        pg_query(
            """
-- Sent/failed rows for the emailed users; every OTHER user with new matches is recorded as
-- skipped_demo (production would email them). notified_at is set for sent + skipped users so
-- they are never emailed twice; failed sends stay un-notified for a later retry.
WITH sent AS (
  SELECT * FROM jsonb_to_recordset($2::jsonb)
         AS s(user_id text, alias_email text, status text, ses_message_id text, error text)
), run AS (
  SELECT job_id FROM pipeline_runs WHERE run_id = $1::uuid
), ins_sent AS (
  INSERT INTO notifications (user_id, alias_email, job_id, run_id, status, ses_message_id, error)
  SELECT user_id::uuid, alias_email, (SELECT job_id FROM run), $1::uuid, status, ses_message_id, error FROM sent
  RETURNING 1
), rest AS (
  SELECT DISTINCT m.user_id FROM matches m
  WHERE m.match_run_id = $1::uuid AND m.status = 'active' AND m.notified_at IS NULL
    AND m.user_id NOT IN (SELECT user_id::uuid FROM sent)
), ins_skip AS (
  INSERT INTO notifications (user_id, alias_email, job_id, run_id, status, error)
  SELECT user_id, '(demo cap: not sent)', (SELECT job_id FROM run), $1::uuid, 'skipped_demo',
         'demo cap reached: production would email this user'
  FROM rest
  RETURNING 1
), mark AS (
  UPDATE matches SET notified_at = now()
  WHERE match_run_id = $1::uuid AND status = 'active' AND notified_at IS NULL
    AND (user_id IN (SELECT user_id::uuid FROM sent WHERE status = 'sent') OR user_id IN (SELECT user_id FROM rest))
  RETURNING 1
)
UPDATE pipeline_runs SET
  emails_sent = (SELECT count(*) FROM sent WHERE status = 'sent'),
  emails_failed = (SELECT count(*) FROM sent WHERE status = 'failed'),
  emails_skipped_demo = (SELECT count(*) FROM rest)
WHERE run_id = $1::uuid
RETURNING emails_sent, emails_failed, emails_skipped_demo,
          (SELECT count(*) FROM mark) AS matches_marked_notified,
          (SELECT count(*) FROM ins_sent) + (SELECT count(*) FROM ins_skip) AS notification_rows
""",
            "={{ [ $json.run_id, JSON.stringify($json.results) ] }}",
        ),
        (1100, -120),
        credentials=PG,
    )

    for a, b in [
        ("Run now (latest run)", "Latest run with new matches"),
        ("Latest run with new matches", "Users to email"),
        ("From B (run)", "Users to email"),
        ("Users to email", "Compose emails"),
        ("Compose emails", "One email at a time"),
        ("Send via AWS SES", "Delivery result"),
        ("Delivery result", "1 email / second (SES sandbox)"),
        ("1 email / second (SES sandbox)", "One email at a time"),
    ]:
        f.link(a, b)
    f.link("One email at a time", "All results -> one item", out=0)  # done
    f.link("All results -> one item", "Record notifications")
    f.link("One email at a time", "Send via AWS SES", out=1)  # loop
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
WITH prev AS (
  SELECT max(created_at) AS last_at FROM workflow_errors WHERE workflow = $1
), ins AS (
  INSERT INTO workflow_errors (workflow, node, message, execution_id)
  VALUES ($1, nullif($2, ''), $3, nullif($4, ''))
  RETURNING id
)
SELECT (SELECT id FROM ins) AS error_id,
       coalesce((SELECT last_at FROM prev) < now() - interval '30 minutes', true) AS should_alert
""",
            "={{ [ $json.workflow, $json.node || '', $json.message, $json.execution_id || '' ] }}",
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
    for filename, wf in (
        ("A_loan_discovery.json", workflow_a()),
        ("A1_process_batch.json", workflow_a1(bucket)),
        ("B_matching.json", workflow_b()),
        ("B1_match_run.json", workflow_b1()),
        ("C_notification.json", workflow_c()),
        ("E_error_handler.json", workflow_e()),
        ("E1_error_drill.json", workflow_e1()),
    ):
        (OUT / filename).write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote n8n/workflows/{filename}: {len(wf['nodes'])} nodes")


if __name__ == "__main__":
    main()
