/**
 * Workflow B, Stage 0: compile free-text criteria into checkable rules (pure functions).
 *
 * Depends on normalize.js (monthlyIncome, ageRange, minCreditScore) and structured.js
 * (jsonList): build_workflows.py pastes them into the Code node. Each text is compiled once and cached in
 * criteria_rules, so LLM cost scales with distinct criteria texts, not with users.
 */

const RULE_FIELDS = ['monthly_income', 'credit_score', 'age'];
const APPLIES_TO = ['any', 'salaried', 'self_employed', 'business'];
// Notes our own pipeline appends to other_criteria_text: never rules or requirements.
const PIPELINE_NOTES = /could not be verified automatically|criteria not published/i;

const squashText = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9₹%]+/g, ' ').trim();

/** Converse request for a batch of criteria texts: [{ text_id, text }]. */
function buildCompileRequest(texts, prompt) {
  const blocks = texts.map((t) => `=== TEXT ${t.text_id} ===\n${String(t.text).slice(0, 3000)}`);
  return {
    system: [{ text: prompt.system }],
    messages: [{ role: 'user', content: [{ text: `${prompt.head}\n\n${blocks.join('\n\n')}` }] }],
    inferenceConfig: { temperature: 0, maxTokens: Math.min(400 * texts.length + 300, 5000) },
  };
}

/** Number for a rule, computed by the tested normalizers (never by the LLM). */
function ruleValue(field, op, valueText) {
  if (field === 'monthly_income') return monthlyIncome(valueText);
  if (field === 'credit_score') return minCreditScore(valueText);
  if (field === 'age') {
    const { min, max } = ageRange(valueText);
    return op === '<=' ? (max ?? min) : (min ?? max);
  }
  return null;
}

/**
 * Validate one compiled text against its source: every rule must have a known field/op,
 * a parseable value, and a quote that appears in the text and contains the value's digits.
 * Anything that fails is demoted to a requirement (shown to the user), never dropped and
 * never used to reject anyone.
 */
function validateCompiled(compiled, sourceText) {
  const page = squashText(sourceText);
  const rules = [];
  const requirements = (compiled.requirements || [])
    .map((r) => String(r).trim())
    .filter((r) => r && !PIPELINE_NOTES.test(r));
  for (const rule of compiled.rules || []) {
    const quote = String(rule.quote || '');
    const value = ruleValue(rule.field, rule.op, rule.value_text);
    const digits = String(rule.value_text || '').match(/\d[\d,.]*/g) || [];
    const ok = RULE_FIELDS.includes(rule.field) && ['>=', '<='].includes(rule.op)
      && APPLIES_TO.includes(rule.applies_to) && value !== null && Number.isFinite(value)
      && quote && page.includes(squashText(quote))
      && digits.every((d) => squashText(quote).includes(squashText(d)));
    if (ok) {
      rules.push({ field: rule.field, op: rule.op, value, applies_to: rule.applies_to, quote });
    } else if (quote && !PIPELINE_NOTES.test(quote)) {
      requirements.push(quote);
    }
  }
  return { rules, requirements: [...new Set(requirements)] };
}

/** Parse the model's answer for a batch; never throws. Returns { byId, ok, error, tokens }. */
function parseCompileResponse(response, texts) {
  const out = { byId: {}, ok: false, error: null, inputTokens: 0, outputTokens: 0 };
  try {
    out.inputTokens = response?.usage?.inputTokens ?? 0;
    out.outputTokens = response?.usage?.outputTokens ?? 0;
    const parsed = jsonList(response);
    const sources = Object.fromEntries(texts.map((t) => [t.text_id, t.text]));
    for (const item of parsed) {
      if (item && item.text_id in sources) out.byId[item.text_id] = validateCompiled(item, sources[item.text_id]);
    }
    out.ok = Object.keys(out.byId).length > 0;
    if (!out.ok) out.error = 'no text_id in the answer matched the request';
  } catch (err) {
    out.error = String(err.message || err).slice(0, 500);
  }
  return out;
}

if (typeof module !== 'undefined') module.exports = { buildCompileRequest, ruleValue, validateCompiled, parseCompileResponse };
