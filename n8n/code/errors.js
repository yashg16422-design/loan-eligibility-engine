/**
 * Workflow E: error handler (pure functions).
 *
 * n8n calls the error workflow with one of two payload shapes:
 *   - execution failed:  { execution: { id, url, retryOf, error: {message, stack}, lastNodeExecuted, mode }, workflow: { id, name } }
 *   - trigger failed:    { trigger: { error: {message, node?}, mode }, workflow: { id, name } }
 * summarizeError() turns either (or garbage) into one flat record, so the rest of the
 * workflow never has to care which shape arrived and can never crash on a missing field.
 */

const MAX_MESSAGE = 2000; // workflow_errors.message: enough for a stack head, bounded for the alert
const ALERT_EVERY_MINUTES = 30; // per workflow: a failing schedule must not drain the SES quota

const clip = (s, n) => {
  const t = String(s ?? '').trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};

function summarizeError(payload) {
  const p = payload && typeof payload === 'object' ? payload : {};
  const exec = p.execution || {};
  const trig = p.trigger || {};
  const err = exec.error || trig.error || {};
  const node = exec.lastNodeExecuted || err.node?.name || (p.trigger ? 'trigger' : null);
  const message = clip(err.message || err.description || 'unknown error (empty error payload)', MAX_MESSAGE);
  return {
    workflow: clip(p.workflow?.name || p.workflow?.id || 'unknown workflow', 200),
    workflow_id: p.workflow?.id ? String(p.workflow.id) : null,
    node: node ? clip(node, 200) : null,
    message,
    execution_id: exec.id != null ? String(exec.id) : null,
    execution_url: /^https?:\/\//i.test(exec.url || '') ? exec.url : null,
    mode: exec.mode || trig.mode || null,
    retry_of: exec.retryOf != null ? String(exec.retryOf) : null,
  };
}

function escapeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

/** Alert email for one error record. Error text can contain crawled HTML: always escaped. */
function composeAlert(rec) {
  const subject = clip(`[loan-engine] ${rec.workflow} failed${rec.node ? ` at "${rec.node}"` : ''}`, 180);
  const rows = [
    ['Workflow', rec.workflow],
    ['Node', rec.node || '-'],
    ['Execution', rec.execution_id || '-'],
    ['Mode', rec.mode || '-'],
    ['Retry of', rec.retry_of || '-'],
  ];
  const html = `<!doctype html><html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:620px">
  <h3 style="color:#b00020;margin-bottom:6px">Workflow failure</h3>
  <table style="border-collapse:collapse;font-size:14px">${rows.map(([k, v]) => `<tr><td style="padding:2px 12px 2px 0;color:#555">${k}</td><td>${escapeText(v)}</td></tr>`).join('')}</table>
  <pre style="background:#f6f6f6;padding:10px;white-space:pre-wrap;font-size:12px">${escapeText(rec.message)}</pre>
  ${rec.execution_url ? `<p><a href="${escapeText(rec.execution_url)}">Open the execution</a> (private n8n: use the SSM tunnel)</p>` : ''}
  <p style="color:#888;font-size:12px">Also stored in the workflow_errors table. Further failures of this workflow are recorded but not emailed for ${ALERT_EVERY_MINUTES} minutes.</p>
</body></html>`;
  return { subject, html };
}

if (typeof module !== 'undefined') module.exports = { MAX_MESSAGE, ALERT_EVERY_MINUTES, summarizeError, composeAlert };
