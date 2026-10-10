/**
 * Workflow C: personalized notification emails (pure functions).
 *
 * Safety rules (CLAUDE.md "Never"):
 *   - Mail goes ONLY to the configured test aliases, never to the CSV address. recipientFor()
 *     picks an alias deterministically and assertAllowed() aborts on anything else.
 *   - Every value from the web (lender names, conditions) is HTML-escaped: a crawled page
 *     must never be able to inject markup into an email.
 * The email is "indicative eligibility, not a loan offer": it explains WHY each product was
 * suggested using the transparent fit score (Stage 3), never an opaque prediction.
 */

const PICKS_IN_EMAIL = 5; // best pick + up to 4 top picks, at most one per lender (decided in SQL)

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

/** Small, stable string hash (FNV-1a 32-bit): same user -> same alias on every run. */
function fnv1a(text) {
  let h = 0x811c9dc5;
  for (const ch of String(text)) { h ^= ch.codePointAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
  return h;
}

function recipientFor(userId, aliases) {
  if (!aliases.length) throw new Error('no test aliases configured');
  return aliases[fnv1a(userId) % aliases.length];
}

/** Abort the send if the recipient is not one of the configured aliases. */
function assertAllowed(recipient, aliases) {
  if (!aliases.includes(recipient)) throw new Error(`refusing to email ${recipient}: not a configured test alias`);
  return recipient;
}

const rupees = (n) => (n == null ? null : `₹${Number(n).toLocaleString('en-IN')}`);

function rateText(p) {
  if (p.interest_rate_min == null) return 'rate on request';
  if (p.interest_rate_max == null || p.interest_rate_max === p.interest_rate_min) return `from ${p.interest_rate_min}% p.a.`;
  return `${p.interest_rate_min}% – ${p.interest_rate_max}% p.a.`;
}

/** One-line "why": every number traces back to a published lender rule. */
function whyText(p) {
  const r = p.fit_reasons || {};
  const parts = [];
  if (r.income_multiple != null) parts.push(`your income is ${r.income_multiple}× the minimum`);
  if (r.credit_margin != null) parts.push(`your credit score is ${r.credit_margin >= 0 ? '+' : ''}${r.credit_margin} vs the minimum`);
  return parts.length ? parts.join(', ') : 'you meet the published criteria';
}

const CHANNEL = { direct: 'on the lender\'s site', bankbazaar: 'via BankBazaar', paisabazaar: 'via Paisabazaar' };

/** A signed dashboard link is shown only if it is a real https URL (never javascript: etc.). */
const safeLink = (url) => (/^https:\/\/[^\s"'<>]+$/i.test(String(url || '')) ? String(url) : null);

/**
 * Subject, HTML and plain-text bodies for one user. `user.picks` is already ranked.
 * `user.dashboard_url` (optional) is the signed "view all my matches" link; when signing
 * failed upstream, the email simply goes out without it.
 */
function composeEmail(user) {
  const picks = (user.picks || []).slice(0, PICKS_IN_EMAIL);
  if (!picks.length) throw new Error(`no picks for user ${user.user_id}`);
  const first = String(user.name || '').trim().split(/\s+/)[0] || 'there';
  const dashboard = safeLink(user.dashboard_url);
  const best = picks[0];
  const subject = `${first}, you may qualify for ${user.lenders_total} personal loan${user.lenders_total === 1 ? '' : 's'} (best: ${best.lender})`;

  const card = (p, i) => {
    const badge = p.tier === 'eligible'
      ? '<span style="background:#e6f4ea;color:#1e7e34;padding:2px 8px;border-radius:10px;font-size:12px">Eligible</span>'
      : '<span style="background:#fff4e5;color:#a35a00;padding:2px 8px;border-radius:10px;font-size:12px">May qualify</span>';
    const needs = p.requirements
      ? `<div style="color:#555;font-size:13px;margin-top:4px">You'll also need: ${escapeHtml(p.requirements).slice(0, 400)}</div>` : '';
    return `<tr><td style="padding:12px 0;border-bottom:1px solid #eee">
      <div style="font-weight:600">${i === 0 ? '⭐ Best pick: ' : ''}${escapeHtml(p.lender)} Personal Loan ${badge}</div>
      <div style="font-size:14px;margin-top:2px">${escapeHtml(rateText(p))} · ${escapeHtml(CHANNEL[p.channel] || p.channel)}${p.loan_amount_max ? ` · up to ${escapeHtml(rupees(p.loan_amount_max))}` : ''}</div>
      <div style="color:#555;font-size:13px;margin-top:4px">Why: ${escapeHtml(whyText(p))}.</div>${needs}
      ${/^https?:\/\//i.test(p.product_url || '') ? `<div style="margin-top:4px"><a href="${escapeHtml(p.product_url)}">View on source</a></div>` : ''}
    </td></tr>`;
  };

  const html = `<!doctype html><html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:620px;margin:auto">
  <h2 style="margin-bottom:4px">Hi ${escapeHtml(first)}, here are your personal-loan matches</h2>
  <p style="color:#555;margin-top:0">Based on your profile (${escapeHtml(rupees(user.monthly_income))}/month, credit score ${escapeHtml(user.credit_score)}, ${escapeHtml(String(user.employment_status).replace('_', '-'))}, age ${escapeHtml(user.age)}) you match <b>${escapeHtml(user.matches_total)}</b> offers from <b>${escapeHtml(user.lenders_total)}</b> lenders. Our top ${picks.length}:</p>
  <table style="width:100%;border-collapse:collapse">${picks.map(card).join('')}</table>
  ${dashboard ? `<p style="margin:20px 0 4px"><a href="${escapeHtml(dashboard)}" style="display:inline-block;background:#F2A93B;color:#1B1305;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600">View all ${escapeHtml(user.matches_total)} matches</a></p>
  <p style="color:#555;font-size:13px;margin-top:6px">Compare offers side by side, see what would unlock more lenders, and save your shortlist. The link works for 14 days.</p>` : ''}
  <p style="color:#888;font-size:12px;margin-top:18px">Indicative eligibility based on criteria published by lenders and comparison sites; not a loan offer or approval. Final eligibility, rates and terms are decided by the lender.<br>
  Demo notice: this test message was routed to a test inbox, not to the address in the uploaded CSV.</p>
</body></html>`;

  const text = [
    `Hi ${first}, here are your personal-loan matches.`,
    `Profile: ${rupees(user.monthly_income)}/month, credit score ${user.credit_score}, ${user.employment_status}, age ${user.age}.`,
    `You match ${user.matches_total} offers from ${user.lenders_total} lenders. Top ${picks.length}:`,
    ...picks.map((p, i) => `${i === 0 ? '* BEST PICK: ' : '- '}${p.lender} (${p.tier === 'eligible' ? 'eligible' : 'may qualify'}) ${rateText(p)} ${CHANNEL[p.channel] || p.channel}. Why: ${whyText(p)}.${p.requirements ? ` Also needed: ${String(p.requirements).slice(0, 300)}` : ''}`),
    ...(dashboard ? [`View all your matches (link valid 14 days): ${dashboard}`] : []),
    'Indicative eligibility, not a loan offer. Demo: routed to a test inbox, not the CSV address.',
  ].join('\n');
  return { subject, html, text };
}

/**
 * Compose (never send) the emails of a batch of users whose real send was skipped by the demo
 * cap: subject + plain text to store. One user's bad data never stops the batch; a user whose
 * matches are gone gets a marker instead, so every row is settled and the loop always ends.
 */
function composeBatch(users) {
  return users.map((user) => {
    if (!user.picks || !user.picks.length) {
      return { user_id: user.user_id, subject: '(not composed: no active matches left)', body_text: '' };
    }
    try {
      const { subject, text } = composeEmail(user);
      return { user_id: user.user_id, subject, body_text: text };
    } catch (err) {
      return { user_id: user.user_id, subject: `(not composed: ${String(err.message).slice(0, 200)})`, body_text: '' };
    }
  });
}

if (typeof module !== 'undefined') module.exports = { PICKS_IN_EMAIL, safeLink, escapeHtml, fnv1a, recipientFor, assertAllowed, whyText, composeEmail, composeBatch };
