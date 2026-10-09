/**
 * Batched criteria extraction with Amazon Nova Pro (Bedrock Converse API), pure functions.
 *
 * ONE request per batch of changed pages (not one per page). The prompt text comes from
 * n8n/prompts/extract_criteria_<version>.md: n8n/build_workflows.py injects it into the
 * Code node, so the prompt file in the repo is the single source of truth.
 * Depends on structured.js (jsonList): the defensive parser shared with compile.js.
 */

const MAX_SECTION_CHARS = 2500;
const MAX_RATES_CHARS = 1200;

/** Converse API body for a batch of pages. `prompt` = { system, head }. */
function buildConverseRequest(pages, prompt) {
  const blocks = pages.map((p) => [
    `=== PAGE ${p.page_id} | source: ${p.channel} | url: ${p.url} ===`,
    '--- ELIGIBILITY SECTION ---',
    String(p.eligibility_text || '').slice(0, MAX_SECTION_CHARS),
    '--- INTEREST RATE SECTION ---',
    String(p.rates_text || '').slice(0, MAX_RATES_CHARS),
  ].join('\n'));
  return {
    system: [{ text: prompt.system }],
    messages: [{ role: 'user', content: [{ text: `${prompt.head}\n\n${blocks.join('\n\n')}` }] }],
    // temperature 0: extraction, not creativity. 900 output tokens per page is ample.
    inferenceConfig: { temperature: 0, maxTokens: Math.min(900 * pages.length + 300, 5000) },
  };
}

/**
 * Parse a Converse response into { extractions: {page_id: obj}, ok, error, tokens }.
 * Never throws: a malformed answer yields ok=false and no extractions, and the caller
 * then stores the pages as unverified/conditional and retries them on the next run.
 */
function parseConverseResponse(response, pageIds) {
  const result = { extractions: {}, ok: false, error: null, inputTokens: 0, outputTokens: 0 };
  try {
    result.inputTokens = response?.usage?.inputTokens ?? 0;
    result.outputTokens = response?.usage?.outputTokens ?? 0;
    for (const item of jsonList(response)) {
      if (item && pageIds.includes(item.page_id)) result.extractions[item.page_id] = item;
    }
    result.ok = Object.keys(result.extractions).length > 0;
    if (!result.ok) result.error = 'no page_id in the answer matched the request';
  } catch (err) {
    result.error = String(err.message || err).slice(0, 500);
  }
  return result;
}

if (typeof module !== 'undefined') module.exports = { buildConverseRequest, parseConverseResponse };
