/**
 * Shared parser for the LLM's JSON answers (pure functions), used by llm.js and compile.js.
 *
 * Why text JSON and not a schema-forced tool call: tested live on 2026-10-09. With
 * toolChoice.tool, Nova Pro calls the tool ONCE and filled the batch array with only 1-2 of
 * 5 pages (text mode: 5/5, and 40/40 on the full crawl). Batching matters more, so the answer
 * stays a JSON array in text, parsed defensively here; the quote verification in
 * normalize.js / compile.js decides what is trusted.
 */

// Placeholder strings mean "not stated": make them real nulls (or drop them from string
// lists) so the normalizers never try to parse the word "null". Nova wrote the text "null"
// in the tool-mode experiment; the prompt forbids it in text mode, this enforces it.
const PLACEHOLDER = /^\s*(null|none|nil|n\/?a|not (stated|mentioned|available|specified)|-+)?\s*$/i;

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize).filter((v) => v !== null);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, sanitize(v)]));
  }
  return typeof value === 'string' && PLACEHOLDER.test(value) ? null : value;
}

/**
 * The JSON array in the model's first text block, tolerating ``` fences and stray prose
 * around it. Throws with a readable reason (callers catch and record it, never crash).
 */
function jsonList(response) {
  const content = response?.output?.message?.content || [];
  const raw = content.find((c) => typeof c?.text === 'string')?.text;
  if (!raw) throw new Error(response?.message || response?.error?.message || 'empty model response');
  const json = raw.trim().replace(/^```(?:json)?\s*|\s*```$/g, '');
  const start = json.indexOf('[');
  const end = json.lastIndexOf(']');
  if (start < 0 || end < start) throw new Error('model did not return a JSON array');
  const list = JSON.parse(json.slice(start, end + 1));
  if (!Array.isArray(list)) throw new Error('model did not return a JSON array');
  return sanitize(list);
}

if (typeof module !== 'undefined') module.exports = { PLACEHOLDER, sanitize, jsonList };
