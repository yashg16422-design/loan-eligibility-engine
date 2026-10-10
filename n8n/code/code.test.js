// Unit tests for the n8n Code-node logic: `node --test n8n/code/code.test.js`
// The SAME files are pasted into the n8n Code nodes, so what is tested is what runs.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const S = require('./sections.js');
const N = require('./normalize.js');

// ------------------------------------------------------------- sections.js

test('htmlToText drops scripts/styles and decodes rupee entities', () => {
  const html = '<style>.x{}</style><p>Income &#8377;25,000</p><script>var a="hidden"</script><div>Age 21</div>';
  const text = S.htmlToText(html);
  assert.match(text, /Income ₹25,000/);
  assert.match(text, /Age 21/);
  assert.doesNotMatch(text, /hidden|\.x\{/);
});

test('embeddedText reads FAQPage ld+json that a naive crawler would strip', () => {
  const html = `<script type="application/ld+json">{"@type":"FAQPage","mainEntity":[{"@type":"Question",
    "name":"What is the minimum salary?","acceptedAnswer":{"@type":"Answer","text":"<p>₹25,000 per month</p>"}}]}</script>`;
  const text = S.embeddedText(html);
  assert.match(text, /minimum salary/);
  assert.match(text, /₹25,000 per month/);
});

test('embeddedText survives malformed JSON blocks', () => {
  assert.equal(S.embeddedText('<script type="application/ld+json">{oops</script>'), '');
});

test('bestWindow skips a navigation menu and picks the real eligibility section', () => {
  const nav = 'Home Loan eligibility | Car Loan eligibility | Credit Cards | About us. '.repeat(3);
  const real = 'Eligibility Criteria Salaried - Age at least 21 and less than 60 years. Minimum income Rs.25,000 per month. CIBIL 750.';
  const { text } = S.bestWindow(`${nav}\n${real}`, 'eligib', { age: 2, money: 2, income: 1, credit: 1 }, 200);
  assert.ok(text.startsWith('Eligibility Criteria Salaried'), text);
});

test('extractSections falls back to the page start when no section scores (layout change)', () => {
  const r = S.extractSections('<p>Totally redesigned page with no recognisable section</p>');
  assert.equal(r.section_found, false);
  assert.match(r.eligibility_text, /redesigned/);
});

// ------------------------------------------------------------- normalize.js

test('lender keys unify names across channels', () => {
  for (const s of ['hdfc', 'hdfc-bank', 'HDFC Bank']) assert.equal(N.lenderKey(s), 'hdfc');
  assert.equal(N.lenderKey('tatacap'), 'tata_capital');
  assert.equal(N.lenderKey('ujjivan'), 'ujjivan');
  assert.equal(N.lenderName('ujjivan'), 'Ujjivan');
});

test('monthlyIncome: units, per-annum, most permissive value', () => {
  const cases = [
    ['₹25,000', 25000],
    ['Rs.25,000 per month', 25000],
    ['₹30,000 or month', 30000], // real typo on a bank page
    ['₹3 lakh p.a.', 25000],
    ['Rs. 6 Lakh per annum', 50000],
    ['15k per month', 15000],
    ['₹25,000 (₹30,000 in metro cities)', 25000],
    ['not mentioned', null],
    // Real ICICI text: business turnover is not a monthly salary -> no income filter
    ['Rs.15 lakh for professionals and Rs.40 lakh for non-professionals as per audited financials', null],
    ['₹15,00,000', 125000], // implausible as monthly -> annual
    [null, null],
  ];
  for (const [raw, want] of cases) assert.equal(N.monthlyIncome(raw), want, String(raw));
});

test('ageRange: inclusive/exclusive bounds and one-sided limits', () => {
  const cases = [
    ['21 years to 60 years', 21, 60],
    ['20–58 years', 20, 58],
    ['Age at least 25 and less than 60', 25, 59],
    ['23 years to 60 or retirement age (whichever earlier)', 23, 60],
    ['Up to 76 years', null, 76],
    ['Minimum 21 years', 21, null],
    // Real ICICI text: several bands -> most permissive (the full text becomes a condition)
    ['25 years (for doctors) and 28 years (for self-employed individuals) to 65 years', 25, 65],
    [null, null, null],
  ];
  for (const [raw, min, max] of cases) assert.deepEqual(N.ageRange(raw), { min, max }, String(raw));
});

test('minCreditScore', () => {
  assert.equal(N.minCreditScore('750 and above'), 750);
  assert.equal(N.minCreditScore('CIBIL 700+'), 700);
  assert.equal(N.minCreditScore('650-900'), 650);
  assert.equal(N.minCreditScore('good credit history'), null);
});

test('rateRange: ranges, onwards, monthly rates, flat', () => {
  assert.deepEqual(N.rateRange('12.75% p.a. - 44% p.a.'), { min: 12.75, max: 44, type: 'unknown' });
  assert.deepEqual(N.rateRange('10.99% onwards'), { min: 10.99, max: null, type: 'unknown' });
  // One stated rate IS the rate (literal reading); monthly -> x12 to compare in % p.a.
  assert.deepEqual(N.rateRange('2.79% per month'), { min: 33.48, max: 33.48, type: 'unknown' });
  assert.equal(N.rateRange('14% flat').type, 'flat');
  assert.deepEqual(N.rateRange(null), { min: null, max: null, type: 'unknown' });
});

test('loan amount and tenure', () => {
  assert.deepEqual(N.loanAmountRange('Up to Rs.5 lakh'), { min: null, max: 500000 });
  assert.deepEqual(N.loanAmountRange('₹50,000 up to ₹50,00,000'), { min: 50000, max: 5000000 });
  assert.equal(N.tenureMaxMonths('12 months to 84 months'), 84);
  assert.equal(N.tenureMaxMonths('up to 5 years'), 60);
});

const SECTION = 'Eligibility Criteria Salaried individuals: Age 21 to 60 years. Minimum monthly income ₹25,000. '
  + 'Age 25 years to 65 years for self-employed 23 years to 60 for salaried individuals.';

test('verifyEntry: genuine quote with its numbers is ok', () => {
  const entry = { employment_type: 'salaried', age: '21 to 60 years', min_income: '₹25,000',
    evidence: 'Salaried individuals: Age 21 to 60 years. Minimum monthly income ₹25,000.' };
  assert.equal(N.verifyEntry(entry, SECTION), 'ok');
});

test('verifyEntry: the IIFL trap (quote names both types) is ambiguous', () => {
  const entry = { employment_type: 'salaried', age: '25 years to 65 years',
    evidence: 'Age 25 years to 65 years for self-employed 23 years to 60 for salaried individuals' };
  assert.equal(N.verifyEntry(entry, SECTION), 'ambiguous');
});

test('verifyEntry: a stitched quote of genuine sentences is ok (real HDFC case)', () => {
  const section = 'Minimum age is 21 years. Employees of PSUs. Minimum income ₹25,000 per month. Other text.';
  const entry = { employment_type: 'any', age: '21 years', min_income: '₹25,000',
    evidence: 'Minimum age is 21 years. Minimum income ₹25,000 per month.' };
  assert.equal(N.verifyEntry(entry, section), 'ok');
});

test('verifyEntry: one invented fragment inside a stitched quote is unverified', () => {
  const section = 'Minimum age is 21 years. Minimum income ₹25,000 per month.';
  const entry = { employment_type: 'any', age: '21 years', min_income: '₹25,000',
    evidence: 'Minimum age is 21 years. CIBIL score of 650 is enough. Minimum income ₹25,000 per month.' };
  assert.equal(N.verifyEntry(entry, section), 'unverified');
});

test('verifyEntry: invented quote or numbers not in the quote are unverified', () => {
  assert.equal(N.verifyEntry({ employment_type: 'any', age: '21 to 60', evidence: 'Age 21 to 65 years' }, SECTION), 'unverified');
  assert.equal(N.verifyEntry({ employment_type: 'any', age: '18 to 60', evidence: 'Age 21 to 60 years' }, SECTION), 'unverified');
  assert.equal(N.verifyEntry({ employment_type: 'any', age: '21 to 60' }, SECTION), 'unverified');
});

test('toProducts: one row per employment type; unverified entries fail safe to conditional', () => {
  const page = {
    channel: 'bankbazaar', lender_slug: 'iifl', url: 'https://example/iifl', eligibility_text: SECTION,
    extraction: {
      interest_rate: '12.75% p.a. - 44% p.a.', loan_amount: 'Up to Rs.5 lakh',
      criteria: [
        { employment_type: 'salaried', age: '21 to 60 years', min_income: '₹25,000', other_conditions: [],
          evidence: 'Salaried individuals: Age 21 to 60 years. Minimum monthly income ₹25,000.' },
        { employment_type: 'self_employed', age: '25 years to 65 years', min_income: null, other_conditions: [],
          evidence: 'Age 25 years to 65 years for self-employed 23 years to 60 for salaried individuals' },
      ],
    },
  };
  const [sal, self] = N.toProducts(page);
  assert.equal(sal.product_name, 'IIFL Finance Personal Loan · via BankBazaar · Salaried');
  assert.deepEqual([sal.min_age, sal.max_age, sal.min_monthly_income], [21, 60, 25000]);
  assert.deepEqual(sal.employment_types, ['salaried']);
  assert.equal(sal.verification, 'ok');
  assert.equal(sal.interest_rate_min, 12.75);
  assert.equal(sal.loan_amount_max, 500000);
  // The ambiguous entry never becomes a hard filter: it is conditional instead.
  assert.equal(self.verification, 'ambiguous');
  assert.deepEqual([self.min_age, self.max_age, self.min_monthly_income], [null, null, null]);
  assert.match(self.other_criteria_text, /could not be verified/);
});

test('toProducts: a page with no criteria still yields one conditional product', () => {
  const [p] = N.toProducts({ channel: 'direct', lender_slug: 'sbi', url: 'u', eligibility_text: '', extraction: {} });
  assert.equal(p.product_name, 'SBI Personal Loan · Direct · All applicants');
  assert.equal(p.employment_types, null);
  assert.match(p.other_criteria_text, /confirm with the lender/);
});

// ------------------------------------------------------------- robots.js
const R = require('./robots.js');

const ROBOTS = `User-agent: GPTBot
Disallow: /

User-agent: *
Disallow: /private/
Allow: /private/public-page
Disallow: /*.pdf$
Disallow: /search?`;

test('robots: the * group applies to us; other bots\' groups do not', () => {
  const ok = { status: 200, body: ROBOTS };
  assert.equal(R.isAllowed('https://x.com/hdfc-personal-loan.html', ok), true);
  assert.equal(R.isAllowed('https://x.com/private/secret', ok), false);
});

test('robots: longest match wins, Allow wins ties; * and $ wildcards', () => {
  const ok = { status: 200, body: ROBOTS };
  assert.equal(R.isAllowed('https://x.com/private/public-page', ok), true);
  assert.equal(R.isAllowed('https://x.com/docs/terms.pdf', ok), false);
  assert.equal(R.isAllowed('https://x.com/docs/terms.pdf?v=2', ok), true); // $ = end of path
  assert.equal(R.isAllowed('https://x.com/search?q=loan', ok), false);
});

test('robots: a group naming our crawler overrides *', () => {
  const body = 'User-agent: *\nDisallow: /\n\nUser-agent: LoanEligibilityEngine\nAllow: /';
  assert.equal(R.isAllowed('https://x.com/a', { status: 200, body }), true);
});

test('robots: fetch status handling (RFC 9309, conservative on 401/403)', () => {
  assert.equal(R.isAllowed('https://x.com/a', { status: 404, body: '' }), true);
  assert.equal(R.isAllowed('https://x.com/a', { status: 403, body: '' }), false);
  assert.equal(R.isAllowed('https://x.com/a', { status: 503, body: '' }), false);
  assert.equal(R.isAllowed('https://x.com/a', null), false); // unreachable
});

// ------------------------------------------------------------- discover.js
const D = require('./discover.js');

test('linksFromHub: lender pages only, absolute URLs, deduplicated, trailing slash for paisabazaar', () => {
  const html = `<a href="/hdfc-personal-loan.html">HDFC</a><a href="/hdfc-personal-loan.html">again</a>
    <a href="https://www.bankbazaar.com/sbi-personal-loan.html">SBI</a>
    <a href="/how-to-track-personal-loan.html">guide</a><a href="/hdfc-personal-loan-emi-calculator.html">EMI</a>`;
  const links = D.linksFromHub(html, 'https://www.bankbazaar.com/personal-loan.html',
    '^https://www\\.bankbazaar\\.com/([a-z0-9-]+)-personal-loan\\.html$');
  assert.deepEqual(links.map((l) => l.lender_slug), ['hdfc', 'sbi']);
  assert.equal(links[0].url, 'https://www.bankbazaar.com/hdfc-personal-loan.html');
  const pb = D.linksFromHub('<a href="/hdfc-bank/personal-loan">x</a><a href="/reviews/personal-loan">r</a>',
    'https://www.paisabazaar.com/personal-loan/', '^https://www\\.paisabazaar\\.com/([a-z0-9-]+)/personal-loan/?$');
  assert.deepEqual(pb, [{ lender_slug: 'hdfc-bank', url: 'https://www.paisabazaar.com/hdfc-bank/personal-loan/' }]);
});

test('roundRobin interleaves channels so one site is never hit back to back', () => {
  const pages = [['bb', 1], ['bb', 2], ['bb', 3], ['pb', 1], ['d', 1]].map(([channel, n]) => ({ channel, n }));
  assert.deepEqual(D.roundRobin(pages).map((p) => `${p.channel}${p.n}`), ['bb1', 'pb1', 'd1', 'bb2', 'bb3']);
});

test('planPages: fixed pages + hub links; a failed hub contributes nothing', () => {
  const sources = [
    { source_id: 'bankbazaar', channel: 'bankbazaar', discovery: 'hub', url: 'https://www.bankbazaar.com/personal-loan.html',
      link_pattern: '^https://www\\.bankbazaar\\.com/([a-z0-9-]+)-personal-loan\\.html$', fetch_mode: 'static' },
    { source_id: 'paisabazaar', channel: 'paisabazaar', discovery: 'hub', url: 'https://www.paisabazaar.com/personal-loan/',
      link_pattern: 'x', fetch_mode: 'static' },
    { source_id: 'direct:icici', channel: 'direct', discovery: 'fixed', url: 'https://icici/pl', lender_slug: 'icici', fetch_mode: 'static' },
  ];
  const pages = D.planPages(sources, { bankbazaar: '<a href="/hdfc-personal-loan.html">' });
  assert.deepEqual(pages.map((p) => `${p.channel}:${p.lender_slug}`), ['bankbazaar:hdfc', 'direct:icici']);
});

// ------------------------------------------------------------- llm.js
Object.assign(globalThis, require('./structured.js'));
const L = require('./llm.js');

test('buildConverseRequest: ONE request for the whole batch, sections truncated, temperature 0', () => {
  const pages = [1, 2, 3].map((i) => ({ page_id: `p${i}`, channel: 'bankbazaar', url: `u${i}`,
    eligibility_text: 'E'.repeat(5000), rates_text: 'R' }));
  const req = L.buildConverseRequest(pages, { system: 'SYS', head: 'HEAD' });
  assert.equal(req.messages.length, 1);
  const text = req.messages[0].content[0].text;
  assert.equal((text.match(/=== PAGE p\d/g) || []).length, 3);
  assert.ok(text.length < 3 * 2600 + 500);
  assert.equal(req.inferenceConfig.temperature, 0);
  assert.equal(req.system[0].text, 'SYS');
});

test('parseConverseResponse: fenced JSON, unknown page ids dropped, tokens kept', () => {
  const response = { usage: { inputTokens: 900, outputTokens: 300 }, output: { message: { content: [{ text:
    '```json\n[{"page_id":"p1","criteria":[]},{"page_id":"zzz"}]\n```' }] } } };
  const r = L.parseConverseResponse(response, ['p1', 'p2']);
  assert.equal(r.ok, true);
  assert.deepEqual(Object.keys(r.extractions), ['p1']);
  assert.equal(r.inputTokens, 900);
});

test('parseConverseResponse never throws on garbage or AWS errors', () => {
  assert.equal(L.parseConverseResponse({ output: { message: { content: [{ text: 'sorry, cannot' }] } } }, ['p1']).ok, false);
  const err = L.parseConverseResponse({ message: 'ThrottlingException' }, ['p1']);
  assert.equal(err.ok, false);
  assert.match(err.error, /Throttling/);
});

// n8n's Code-node sandbox has no `URL` global (seen live: "URL is not defined").
// Run every module's functions with URL removed to make sure none of them depends on it.
test('modules work without the URL global (n8n sandbox)', () => {
  const saved = globalThis.URL;
  try {
    globalThis.URL = undefined;
    assert.equal(R.pathOf('https://x.com/a/b?q=1#frag'), '/a/b?q=1');
    assert.equal(R.pathOf('https://x.com'), '/');
    assert.equal(R.isAllowed('https://x.com/private/x', { status: 200, body: ROBOTS }), false);
    assert.equal(D.linksFromHub('<a href="/hdfc-personal-loan.html">', 'https://www.bankbazaar.com/personal-loan.html',
      '^https://www\\.bankbazaar\\.com/([a-z0-9-]+)-personal-loan\\.html$').length, 1);
    assert.ok(S.extractSections('<p>Eligibility Age 21 to 60 years income Rs.25,000</p>'));
  } finally {
    globalThis.URL = saved;
  }
});

test('toProducts keeps the exact wording when the hard filter simplified (real ICICI case)', () => {
  const evidence = 'Age 25 years (for doctors) and 28 years (for self-employed individuals) to 65 years Minimum turnover Rs.15 lakh for professionals and Rs.40 lakh for non-professionals as per audited financials';
  const [row] = N.toProducts({ channel: 'bankbazaar', lender_slug: 'icici', url: 'u', eligibility_text: evidence, extraction: {
    criteria: [{ employment_type: 'self_employed', evidence,
      age: '25 years (for doctors) and 28 years (for self-employed individuals) to 65 years',
      min_income: 'Rs.15 lakh for professionals and Rs.40 lakh for non-professionals as per audited financials',
      other_conditions: [] }] } });
  assert.deepEqual([row.min_age, row.max_age, row.min_monthly_income], [25, 65, null]);
  assert.match(row.other_criteria_text, /Age: 25 years \(for doctors\)/);
  assert.match(row.other_criteria_text, /Business criteria: Rs\.15 lakh/);
});

// ------------------------------------------------------------- compile.js (Stage 0)
// compile.js uses normalize.js's functions as globals (in n8n both files share one Code node).
Object.assign(globalThis, require('./normalize.js'));
const C = require('./compile.js');

const CRITERIA = 'Minimum CIBIL score of 750. Salaried applicants must be at most 60 years old. '
  + 'Net income of ₹30,000 for metro cities. 2 years work experience.';

test('validateCompiled: genuine rules get numeric values from the normalizers', () => {
  const r = C.validateCompiled({
    rules: [
      { field: 'credit_score', op: '>=', value_text: '750', applies_to: 'any', quote: 'Minimum CIBIL score of 750' },
      { field: 'age', op: '<=', value_text: '60 years', applies_to: 'salaried', quote: 'must be at most 60 years old' },
    ],
    requirements: ['Net income of ₹30,000 for metro cities', '2 years work experience'],
  }, CRITERIA);
  assert.deepEqual(r.rules.map((x) => [x.field, x.op, x.value, x.applies_to]),
    [['credit_score', '>=', 750, 'any'], ['age', '<=', 60, 'salaried']]);
  assert.equal(r.requirements.length, 2);
});

test('validateCompiled: an invented or unparseable rule is demoted to a requirement, never a rejection', () => {
  const r = C.validateCompiled({
    rules: [
      { field: 'credit_score', op: '>=', value_text: '800', applies_to: 'any', quote: 'Minimum CIBIL score of 800' }, // not in text
      { field: 'monthly_income', op: '>=', value_text: 'a good salary', applies_to: 'any', quote: '2 years work experience' },
      { field: 'city', op: '>=', value_text: '1', applies_to: 'any', quote: 'metro cities' },
    ],
    requirements: [],
  }, CRITERIA);
  assert.deepEqual(r.rules, []);
  assert.ok(r.requirements.includes('2 years work experience'));
});

test('validateCompiled ignores the pipeline\'s own notes', () => {
  const r = C.validateCompiled({ rules: [], requirements: [
    'Eligibility details could not be verified automatically: confirm with the lender', 'Salary account needed'] }, 'x');
  assert.deepEqual(r.requirements, ['Salary account needed']);
});

test('parseCompileResponse maps answers back by text_id and never throws', () => {
  const texts = [{ text_id: 't1', text: CRITERIA }];
  const ok = C.parseCompileResponse({ usage: { inputTokens: 10, outputTokens: 5 }, output: { message: { content: [{ text:
    '[{"text_id":"t1","rules":[{"field":"credit_score","op":">=","value_text":"750","applies_to":"any","quote":"Minimum CIBIL score of 750"}],"requirements":[]}]' }] } } }, texts);
  assert.equal(ok.ok, true);
  assert.equal(ok.byId.t1.rules[0].value, 750);
  assert.equal(C.parseCompileResponse({ message: 'AccessDenied' }, texts).ok, false);
  const req = C.buildCompileRequest(texts, { system: 'S', head: 'H' });
  assert.match(req.messages[0].content[0].text, /=== TEXT t1 ===/);
});

// ------------------------------------------------------------- email.js (Workflow C)
const E = require('./email.js');
const ALIASES = ['tester+one@gmail.com', 'tester+two@gmail.com', 'tester+three@gmail.com'];
const USER = {
  user_id: 'b35de23e-755f-4c6a-81d8-f7dd99ce53ef', name: 'Dhruv Iyengar', monthly_income: 131000, credit_score: 725,
  employment_status: 'self_employed', age: 37, matches_total: 31, lenders_total: 18,
  picks: [
    { lender: 'ICICI Bank', channel: 'direct', tier: 'eligible', interest_rate_min: 9.99, interest_rate_max: 16.5,
      fit_reasons: { income_multiple: 4.4, credit_margin: 25 }, requirements: null, product_url: 'https://x/icici', loan_amount_max: 5000000 },
    { lender: 'Evil <script>alert(1)</script> Bank', channel: 'bankbazaar', tier: 'conditional', interest_rate_min: 12,
      fit_reasons: {}, requirements: '2 years experience <img src=x onerror=alert(1)>', product_url: 'javascript:alert(1)"' },
  ],
};

test('recipientFor is deterministic and always one of the aliases', () => {
  const a = E.recipientFor(USER.user_id, ALIASES);
  assert.equal(a, E.recipientFor(USER.user_id, ALIASES));
  assert.ok(ALIASES.includes(a));
  const spread = new Set(Array.from({ length: 30 }, (_, i) => E.recipientFor(`user-${i}`, ALIASES)));
  assert.equal(spread.size, 3); // users are spread over all aliases
});

test('assertAllowed refuses anything that is not a configured alias (e.g. the CSV address)', () => {
  assert.throws(() => E.assertAllowed('dhruv.iyengar@example.com', ALIASES), /refusing/);
  assert.equal(E.assertAllowed(ALIASES[1], ALIASES), ALIASES[1]);
});

test('composeEmail: personalized, ranked, explained, and every crawled value is escaped', () => {
  const { subject, html, text } = E.composeEmail(USER);
  assert.equal(subject, 'Dhruv, you may qualify for 18 personal loans (best: ICICI Bank)');
  assert.match(html, /⭐ Best pick: ICICI Bank/);
  assert.match(html, /4\.4× the minimum/);
  assert.match(html, /not a loan offer/);
  assert.doesNotMatch(html, /<script>|<img src=x/); // injected markup is neutralised
  assert.match(html, /&lt;script&gt;/);
  assert.match(text, /\* BEST PICK: ICICI Bank/);
  assert.doesNotMatch(html, /href="javascript/i); // only http(s) links are rendered
  assert.match(html, /href="https:\/\/x\/icici"/);
});

test('composeEmail refuses to build an empty email', () => {
  assert.throws(() => E.composeEmail({ ...USER, picks: [] }), /no picks/);
});

// ------------------------------------------------------------- errors.js

const ER = require('./errors.js');

test('summarizeError: execution failure payload (documented n8n shape)', () => {
  const rec = ER.summarizeError({
    execution: { id: 231, url: 'http://10.0.0.201:5678/execution/231', retryOf: '34',
      error: { message: 'connect ETIMEDOUT', stack: 'Error: ...' }, lastNodeExecuted: 'Claim job + start run', mode: 'webhook' },
    workflow: { id: 'LoanEngineWfB001', name: 'B · User-loan matching' },
  });
  assert.deepEqual(rec, {
    workflow: 'B · User-loan matching', workflow_id: 'LoanEngineWfB001', node: 'Claim job + start run',
    message: 'connect ETIMEDOUT', execution_id: '231', execution_url: 'http://10.0.0.201:5678/execution/231',
    mode: 'webhook', retry_of: '34',
  });
});

test('summarizeError: trigger failure payload has no execution', () => {
  const rec = ER.summarizeError({
    trigger: { error: { message: 'Workflow could not be activated', node: { name: 'Sweeper every 10 min' } }, mode: 'trigger' },
    workflow: { id: 'LoanEngineWfB001', name: 'B · User-loan matching' },
  });
  assert.equal(rec.node, 'Sweeper every 10 min');
  assert.equal(rec.execution_id, null);
  assert.equal(rec.mode, 'trigger');
  assert.match(rec.message, /could not be activated/);
});

test('summarizeError never throws and bounds the message', () => {
  for (const junk of [undefined, null, 'x', 42, {}, { execution: null }, { execution: { error: null } }]) {
    const rec = ER.summarizeError(junk);
    assert.equal(rec.workflow, 'unknown workflow');
    assert.match(rec.message, /unknown error/);
  }
  const long = ER.summarizeError({ execution: { error: { message: 'x'.repeat(10000) } } });
  assert.equal(long.message.length, ER.MAX_MESSAGE);
  assert.equal(ER.summarizeError({ execution: { url: 'javascript:alert(1)' } }).execution_url, null);
});

test('composeAlert escapes error text (it can contain crawled HTML)', () => {
  const rec = ER.summarizeError({ execution: { error: { message: '<img src=x onerror=alert(1)>' }, lastNodeExecuted: '<b>n</b>' },
    workflow: { name: 'A1' } });
  const { subject, html } = ER.composeAlert(rec);
  assert.match(subject, /A1 failed at "<b>n<\/b>"/); // subject is plain text, not HTML
  assert.doesNotMatch(html, /<img|<b>n/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

// ------------------------------------------------------------- structured.js (shared parser)

const ST = require('./structured.js');

test('requests are plain text-JSON: no forced tool (Nova filled 1 of 5 pages in tool mode)', () => {
  assert.equal(L.buildConverseRequest([{ page_id: 'p1' }], { system: 'S', head: 'H' }).toolConfig, undefined);
  assert.equal(C.buildCompileRequest([{ text_id: 't', text: 'x' }], { system: 'S', head: 'H' }).toolConfig, undefined);
});

test('sanitize: placeholder strings become null, string lists drop them', () => {
  assert.deepEqual(ST.sanitize({ a: 'null', b: ' N/A ', c: '', d: 'Not mentioned', e: '₹25,000', f: 0, g: ['x', 'null', 'none'] }),
    { a: null, b: null, c: null, d: null, e: '₹25,000', f: 0, g: ['x'] });
  assert.equal(ST.sanitize('nullable income'), 'nullable income'); // only whole-value placeholders
});

test('jsonList: fences and prose around the array are tolerated; placeholders sanitized', () => {
  const r = (text) => ({ output: { message: { content: [{ text }] } } });
  assert.deepEqual(ST.jsonList(r('Here you go:\n```json\n[{"page_id":"p1","fee":"N/A"}]\n```')), [{ page_id: 'p1', fee: null }]);
  assert.throws(() => ST.jsonList(r('{"page_id":"p1"}')), /did not return a JSON array/);
  assert.throws(() => ST.jsonList(r('] nothing [')), /did not return a JSON array/);
  assert.throws(() => ST.jsonList({ message: 'ThrottlingException' }), /ThrottlingException/);
});

test('parseConverseResponse turns "null" text into a real null before the normalizers see it', () => {
  const res = { output: { message: { content: [{ text: '[{"page_id":"p1","processing_fee":"null","criteria":[{"employment_type":"any","min_income":"null","other_conditions":["null"],"evidence":"Age 21"}]}]' }] } } };
  const e = L.parseConverseResponse(res, ['p1']).extractions.p1;
  assert.equal(e.processing_fee, null);
  assert.equal(e.criteria[0].min_income, null);
  assert.deepEqual(e.criteria[0].other_conditions, []);
});

test('composeEmail adds the signed dashboard link only when it is a safe https URL', () => {
  const link = 'https://t7lcgp5o0j.execute-api.ap-southeast-2.amazonaws.com/app/dashboard?t=abc.123.sig';
  const withLink = E.composeEmail({ ...USER, dashboard_url: link });
  assert.match(withLink.html, /View all \d+ matches/);
  assert.ok(withLink.html.includes(`href="${link}"`));
  assert.ok(withLink.text.includes(link));
  for (const bad of [undefined, '', 'javascript:alert(1)', 'http://plain.example/app', 'https://x.com/"><script>']) {
    const out = E.composeEmail({ ...USER, dashboard_url: bad });
    assert.doesNotMatch(out.html, /View all \d+ matches/);
    assert.doesNotMatch(out.html, /<script>/);
  }
});

// ------------------------------------------------------------- DF7: unverified conditions never become rules

test('toProducts: a condition the model listed but the page does not say is marked, not trusted', () => {
  const page = {
    channel: 'bankbazaar', lender_slug: 'hdfc', url: 'https://www.bankbazaar.com/hdfc-personal-loan.html',
    eligibility_text: 'Age 21 to 60 years. Minimum income Rs. 25,000 per month. Minimum work experience of 2 years.',
    rates_text: '',
    extraction: { criteria: [{ employment_type: 'any', age: '21 to 60 years', min_income: 'Rs. 25,000 per month',
      other_conditions: ['Minimum work experience of 2 years', 'CIBIL score of 750 required'],
      evidence: 'Age 21 to 60 years. Minimum income Rs. 25,000 per month.' }] },
  };
  const [row] = N.toProducts(page);
  assert.equal(row.verification, 'ok');
  assert.match(row.other_criteria_text, /^Minimum work experience of 2 years; Also mentioned but not verified on the page: CIBIL score of 750 required$/);
});

test('compile: the LLM sees only verified text; an invented rule is impossible; the rest is a requirement', () => {
  assert.equal(C.UNVERIFIED_MARK, N.UNVERIFIED_MARK); // the two modules agree on the marker
  const text = 'Minimum work experience of 2 years; Also mentioned but not verified on the page: CIBIL score of 750 required';
  assert.deepEqual(C.splitConditions(text), {
    checkable: 'Minimum work experience of 2 years',
    unverified: 'Also mentioned but not verified on the page: CIBIL score of 750 required',
  });
  const req = C.buildCompileRequest([{ text_id: 't', text }], { system: 'S', head: 'H' });
  assert.doesNotMatch(req.messages[0].content[0].text, /CIBIL/);
  // Even if the model invents the rule, its quote is not in the verified text, so it is not a rule.
  const res = { output: { message: { content: [{ text: JSON.stringify([{ text_id: 't', requirements: [],
    rules: [{ field: 'credit_score', op: '>=', value_text: '750', applies_to: 'any', quote: 'CIBIL score of 750 required' }] }]) }] } } };
  const out = C.parseCompileResponse(res, [{ text_id: 't', text }]);
  assert.deepEqual(out.byId.t.rules, []);
  assert.ok(out.byId.t.requirements.some((r) => r.startsWith('Also mentioned but not verified')));
  // Nothing verifiable at all: no model answer needed, still never a rule.
  const only = 'Also mentioned but not verified on the page: CIBIL score of 750 required';
  const none = C.parseCompileResponse({ output: { message: { content: [{ text: '[]' }] } } }, [{ text_id: 'u', text: only }]);
  assert.deepEqual(none.byId.u, { rules: [], requirements: [only] });
});

test('compile: a lender that publishes no criteria is "may qualify", never plainly eligible', () => {
  // Live bug: Federal Bank (Paisabazaar) publishes nothing; the note was filtered out, the text
  // compiled to no rules and no requirements, and all 10,000 users showed as eligible.
  const note = 'Eligibility criteria not published: confirm with the lender';
  const r = C.validateCompiled({ rules: [], requirements: [] }, note);
  assert.deepEqual(r, { rules: [], requirements: [note] });
  const mixed = C.validateCompiled({ rules: [], requirements: ['Salary account needed'] },
    `Salary account needed; ${note}`);
  assert.deepEqual(mixed.requirements, ['Salary account needed', note]);
  assert.deepEqual(C.pipelineNotes('a; Eligibility details could not be verified automatically: confirm with the lender'),
    ['Eligibility details could not be verified automatically: confirm with the lender']);
});
