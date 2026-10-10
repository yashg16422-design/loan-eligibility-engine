/**
 * Workflow A, Code node "Verify + normalize" (PLAN.md §10.2 steps 5-7).
 *
 * The LLM extracts raw strings; THIS code does the math, deterministically:
 *   "₹3 lakh p.a." -> 25000 (monthly), "21 to 60 years" -> {21, 60}, "10.99% onwards" -> 10.99
 * and it verifies the LLM: every criteria entry must quote evidence that really appears
 * in the page and contains the numbers it claims. Unverifiable or ambiguous entries are
 * NOT used as hard filters: they become "conditional: confirm with lender" (fail safe).
 *
 * Pure functions; pasted into the Code node by n8n/build_workflows.py, tested by node --test.
 * Input item:  { channel, lender_slug, url, eligibility_text, rates_text, extraction }
 * Output: one item per product row (lender x channel x employment type).
 */

const LAKH = 100000;
const CRORE = 10000000;

// Canonical lender keys: "HDFC", "hdfc-bank", "HDFC Bank Ltd" -> "hdfc".
const LENDER_ALIASES = {
  hdfc: ['hdfc', 'hdfc-bank'], icici: ['icici', 'icici-bank'], axis: ['axis', 'axis-bank'],
  sbi: ['sbi', 'sbi-bank', 'state-bank-of-india'], kotak: ['kotak', 'kotak-mahindra-bank', 'kotak-mahindra'],
  idfc_first: ['idfc', 'idfc-bank', 'idfc-first', 'idfc-first-bank'], indusind: ['indusind', 'indusind-bank'],
  tata_capital: ['tatacap', 'tata-capital'], rbl: ['rbl', 'rbl-bank'], yes_bank: ['yes', 'yes-bank'],
  federal: ['federal', 'federal-bank'], hdb_financial: ['hdbfs', 'hdb-financial'], iifl: ['iifl', 'iifl-finance'],
  pnb: ['pnb', 'punjab-national-bank'], bank_of_baroda: ['bank-of-baroda', 'bob'],
  standard_chartered: ['standard-chartered', 'standard-chartered-bank'],
};
const LENDER_NAMES = {
  hdfc: 'HDFC Bank', icici: 'ICICI Bank', axis: 'Axis Bank', sbi: 'SBI', kotak: 'Kotak Mahindra Bank',
  idfc_first: 'IDFC FIRST Bank', indusind: 'IndusInd Bank', tata_capital: 'Tata Capital', rbl: 'RBL Bank',
  yes_bank: 'YES Bank', federal: 'Federal Bank', hdb_financial: 'HDB Financial Services', iifl: 'IIFL Finance',
  pnb: 'Punjab National Bank', bank_of_baroda: 'Bank of Baroda', standard_chartered: 'Standard Chartered',
};
const CHANNEL_LABELS = { direct: 'Direct', bankbazaar: 'via BankBazaar', paisabazaar: 'via Paisabazaar' };
const EMPLOYMENT = { salaried: 'Salaried', self_employed: 'Self-employed', business: 'Business', any: 'All applicants' };
const EMPLOYMENT_WORDS = {
  salaried: /\bsalaried\b/i, self_employed: /self[- ]?employed/i, business: /\bbusiness\b/i,
};

function lenderKey(slug) {
  const s = String(slug || '').toLowerCase().trim().replace(/[\s_]+/g, '-');
  for (const [key, aliases] of Object.entries(LENDER_ALIASES)) if (aliases.includes(s)) return key;
  return s.replace(/-/g, '_');
}

function lenderName(key) {
  return LENDER_NAMES[key] || key.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

/** "50,00,000" / "25,000" / "3.5" -> number (Indian digit grouping is just commas). */
function num(s) { return Number(String(s).replace(/,/g, '')); }

/** Every amount in a string, in rupees, honouring lakh/crore/k multipliers. */
function amounts(raw) {
  const out = [];
  const re = /(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|l\b|crores?|cr\b|k\b|thousand)?/gi;
  let m;
  while ((m = re.exec(String(raw || ''))) !== null) {
    let v = num(m[1]);
    const unit = (m[2] || '').toLowerCase();
    if (/^(lakh|lac|l$)/.test(unit)) v *= LAKH;
    else if (/^(crore|cr)/.test(unit)) v *= CRORE;
    else if (unit === 'k' || unit === 'thousand') v *= 1000;
    if (Number.isFinite(v) && v > 0) out.push(v);
  }
  return out;
}

/**
 * Minimum income -> rupees PER MONTH. "p.a."/"annual" values are divided by 12.
 * Several values (e.g. "₹25,000; ₹30,000 in metro cities") -> the MOST PERMISSIVE
 * (lowest) goes into the hard filter; the condition text is kept separately.
 */
// Business-size criteria (turnover, ITR, audited financials, profit) are not a salary:
// they cannot be compared with a user's monthly income, so they become conditions.
const NOT_INCOME = /turnover|itr|income tax return|audited|financials|profit|gross receipts/i;
const MAX_PLAUSIBLE_MONTHLY = 1000000; // ₹10 lakh/month: anything above is surely an annual figure

function monthlyIncome(raw) {
  if (!raw || NOT_INCOME.test(raw)) return null;
  const values = amounts(raw).filter((v) => v >= 1000);
  if (!values.length) return null;
  const yearly = /p\.?\s?a\b|per annum|annual|annually|yearly|a year|per year/i.test(raw);
  const monthly = Math.min(...values) / (yearly ? 12 : 1);
  return Math.round(monthly > MAX_PLAUSIBLE_MONTHLY ? monthly / 12 : monthly);
}

/** "21 to 60 years", "Age at least 25 and less than 60", "Up to 76 years" -> {min, max}. */
function ageRange(raw) {
  if (!raw) return { min: null, max: null };
  const s = String(raw).toLowerCase();
  const nums = (s.match(/\d{2}/g) || []).map(Number).filter((n) => n >= 18 && n <= 100);
  if (!nums.length) return { min: null, max: null };
  // "less than 60" / "below 60" / "under 60" are exclusive upper bounds.
  const exclusiveMax = /(less than|below|under)\s*(\d{2})/.exec(s);
  const onlyMax = /^(?:\D*)(up ?to|max(?:imum)?|not more than|less than|below|under)\b/.test(s) && nums.length === 1;
  const onlyMin = /(at least|minimum|min\.?|above|over|\+|and above|or above)/.test(s) && nums.length === 1;
  // Several bands ("25 (doctors) and 28 (others) to 65") -> the most permissive range goes
  // into the hard filter; toProducts keeps the full text as a condition.
  let min = nums.length >= 2 ? Math.min(...nums) : null;
  let max = nums.length >= 2 ? Math.max(...nums) : null;
  if (nums.length === 1) { if (onlyMax) max = nums[0]; else if (onlyMin) min = nums[0]; else min = nums[0]; }
  if (exclusiveMax && Number(exclusiveMax[2]) === max) max -= 1;
  if (exclusiveMax && nums.length === 1) { min = null; max = Number(exclusiveMax[2]) - 1; }
  return { min, max };
}

/** "750 and above", "CIBIL 700+", "650-900" -> minimum score (300..900), else null. */
function minCreditScore(raw) {
  if (!raw) return null;
  const nums = (String(raw).match(/\d{3}/g) || []).map(Number).filter((n) => n >= 300 && n <= 900);
  return nums.length ? Math.min(...nums) : null;
}

/** "10.99% - 24% p.a.", "10.99% onwards", "2.79% per month" -> {min, max, type} in % p.a. */
function rateRange(raw) {
  if (!raw) return { min: null, max: null, type: 'unknown' };
  const s = String(raw);
  let rates = (s.match(/\d{1,2}(?:\.\d{1,2})?(?=\s*%)/g) || []).map(Number);
  if (/per month|p\.?\s?m\b|monthly/i.test(s)) rates = rates.map((r) => Math.round(r * 12 * 100) / 100);
  rates = rates.filter((r) => r > 0 && r < 100);
  const type = /flat/i.test(s) ? 'flat' : /reducing/i.test(s) ? 'reducing' : 'unknown';
  if (!rates.length) return { min: null, max: null, type };
  const onwards = /onwards|starting|from|min/i.test(s) && rates.length === 1;
  return { min: Math.min(...rates), max: onwards ? null : Math.max(...rates), type };
}

/** "Up to ₹50 lakh", "₹50,000 to ₹50,00,000" -> {min, max} in rupees. */
function loanAmountRange(raw) {
  const v = amounts(raw).filter((x) => x >= 1000);
  if (!v.length) return { min: null, max: null };
  return v.length === 1 ? { min: null, max: v[0] } : { min: Math.min(...v), max: Math.max(...v) };
}

/** "12 months to 84 months", "up to 5 years" -> max tenure in months. */
function tenureMaxMonths(raw) {
  if (!raw) return null;
  const s = String(raw).toLowerCase();
  const months = (s.match(/(\d{1,3})\s*months?/g) || []).map((x) => parseInt(x, 10));
  const years = (s.match(/(\d{1,2})\s*(?:years?|yrs)/g) || []).map((x) => parseInt(x, 10) * 12);
  const all = [...months, ...years].filter((n) => n > 0 && n <= 360);
  return all.length ? Math.max(...all) : null;
}

const squash = (s) => String(s || '').toLowerCase().replace(/&#x27;|&#39;/g, "'").replace(/[^a-z0-9₹%]+/g, ' ').trim();

/**
 * Check one LLM criteria entry against the page text.
 *   - every sentence fragment of the evidence quote must occur verbatim in the page
 *     sections (anti-hallucination; stitched multi-sentence quotes are fine);
 *   - every number in age/min_income/credit_score must occur in the evidence;
 *   - for a specific employment type, the evidence must name it and no OTHER type
 *     (a quote that mentions both cannot prove which band belongs to which).
 * Returns 'ok' | 'ambiguous' | 'unverified'.
 */
function verifyEntry(entry, sectionText) {
  const evidence = String(entry.evidence || '');
  const page = squash(sectionText);
  // Models often stitch several sentences into one quote. Accept that, but every
  // fragment must still appear verbatim on the page: an invented fragment fails.
  const fragments = evidence.split(/[.;\n•|]+/).map(squash).filter((f) => f.length >= 8);
  if (!fragments.length || !fragments.every((f) => page.includes(f))) return 'unverified';
  for (const field of ['age', 'min_income', 'credit_score']) {
    for (const n of String(entry[field] || '').match(/\d[\d,.]*/g) || []) {
      if (!squash(evidence).includes(squash(n))) return 'unverified';
    }
  }
  const type = entry.employment_type;
  if (EMPLOYMENT_WORDS[type]) {
    const mentionsOwn = EMPLOYMENT_WORDS[type].test(evidence);
    const others = Object.entries(EMPLOYMENT_WORDS).filter(([t, re]) => t !== type && re.test(evidence));
    // "Salaried individuals: 21-60" is ok; "25-65 for self-employed, 23-60 for salaried" is not provable.
    if (others.length && !(mentionsOwn && others.every(([t]) => t === 'business' && type === 'self_employed'))) {
      return 'ambiguous';
    }
  }
  return 'ok';
}

const UNVERIFIED_NOTE = 'Eligibility details could not be verified automatically: confirm with the lender';
// Conditions the model listed that do not appear on the page: shown to the user, but never
// compiled into a rule (compile.js only reads the text BEFORE this marker), so an invented
// phrase can never reject anyone. Keep identical to UNVERIFIED_MARK in compile.js.
const UNVERIFIED_MARK = 'Also mentioned but not verified on the page:';

/** True when every fragment of a phrase occurs verbatim in the page sections. */
function onPage(phrase, sectionText) {
  const page = squash(sectionText);
  const whole = squash(phrase);
  if (!whole) return false;
  const fragments = String(phrase).split(/[.;\n•|]+/).map(squash).filter((f) => f.length >= 8);
  return fragments.length ? fragments.every((f) => page.includes(f)) : page.includes(whole);
}

/** One extraction (one page) -> product rows ready for the loan_products upsert. */
function toProducts(page) {
  const x = page.extraction || {};
  const key = lenderKey(page.lender_slug);
  const name = lenderName(key);
  const rate = rateRange(x.interest_rate);
  const amount = loanAmountRange(x.loan_amount);
  const entries = Array.isArray(x.criteria) && x.criteria.length ? x.criteria : [{ employment_type: 'any', other_conditions: [] }];
  return entries.map((entry) => {
    const type = EMPLOYMENT[entry.employment_type] ? entry.employment_type : 'any';
    const check = verifyEntry(entry, `${page.eligibility_text || ''}\n${page.rates_text || ''}`); // evidence
    const trusted = check === 'ok';
    const age = trusted ? ageRange(entry.age) : { min: null, max: null };
    const sections = `${page.eligibility_text || ''}\n${page.rates_text || ''}`;
    const listed = (entry.other_conditions || []).map((c) => String(c).trim()).filter(Boolean);
    const conditions = listed.filter((c) => onPage(c, sections));
    const notOnPage = listed.filter((c) => !onPage(c, sections));
    if (!trusted) conditions.push(UNVERIFIED_NOTE);
    // When the hard filter had to simplify, the exact wording still reaches the user.
    if (trusted && entry.age && (String(entry.age).match(/\d{2}/g) || []).length > 2) conditions.push(`Age: ${entry.age}`);
    if (trusted && entry.min_income && NOT_INCOME.test(entry.min_income)) conditions.push(`Business criteria: ${entry.min_income}`);
    // A lender that publishes NO criteria is never shown as plainly "eligible".
    if (trusted && !entry.age && !entry.min_income && !entry.credit_score) {
      conditions.push('Eligibility criteria not published: confirm with the lender');
    }
    if (notOnPage.length) conditions.push(`${UNVERIFIED_MARK} ${notOnPage.join(', ')}`); // always last
    return {
      lender: name,
      lender_key: key,
      channel: page.channel,
      source_url: page.url,
      product_name: `${name} Personal Loan · ${CHANNEL_LABELS[page.channel] || page.channel} · ${EMPLOYMENT[type]}`,
      product_url: page.url,
      interest_rate_min: rate.min,
      interest_rate_max: rate.max,
      rate_type: rate.type,
      min_monthly_income: trusted ? monthlyIncome(entry.min_income) : null,
      min_credit_score: trusted ? minCreditScore(entry.credit_score) : null,
      max_credit_score: null,
      min_age: age.min,
      max_age: age.max,
      employment_types: type === 'any' ? null : [type],
      loan_amount_min: amount.min,
      loan_amount_max: amount.max,
      tenure_months_max: tenureMaxMonths(x.tenure),
      other_criteria_text: conditions.length ? conditions.join('; ') : null,
      verification: check,
      raw_extracted: { ...x, criteria: [entry] },
    };
  });
}

// Exported for `node --test`; inside n8n there is no `module`, so this is skipped.
// Bump when this file's output changes for the same input: it is part of the page hash,
// so every page is re-normalized once (Workflow A re-extracts changed-hash pages).
const NORMALIZER_VERSION = 3;

if (typeof module !== 'undefined') module.exports = {
  NORMALIZER_VERSION, lenderKey, lenderName, amounts, monthlyIncome, ageRange, minCreditScore, rateRange,
  loanAmountRange, tenureMaxMonths, verifyEntry, onPage, UNVERIFIED_MARK, toProducts,
};
