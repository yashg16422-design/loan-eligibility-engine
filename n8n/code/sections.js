/**
 * Workflow A, Code node "Isolate sections" (PLAN.md §10.2 step 3).
 *
 * Pure functions only. n8n/build_workflows.py pastes this file into the Code node and
 * appends the node's entry snippet; `node --test n8n/code/code.test.js` tests the same functions.
 * So the code that is tested is exactly the code that runs. No external modules.
 *
 * Input item:  { html, channel, lender_slug, url, ... }
 * Output item: input + { eligibility_text, rates_text, section_found, text_chars }
 */

const SIGNALS = {
  age: /\b(?:1[89]|[2-7]\d)\s*(?:years?|yrs)\b/gi,
  money: /(?:₹|rs\.?|inr)\s?[\d,]{4,}|\d+(?:\.\d+)?\s*(?:lakh|lac)\b/gi,
  income: /income|salary|earning/gi,
  credit: /cibil|credit score/gi,
  employment: /salaried|self[- ]employed|business/gi,
  rate: /\d{1,2}(?:\.\d{1,2})?\s*%/g,
};

const ENTITIES = { '&nbsp;': ' ', '&amp;': '&', '&#8377;': '₹', '&#x20b9;': '₹', '&#39;': "'", '&#x27;': "'", '&quot;': '"', '&lt;': '<', '&gt;': '>' };

/** Visible text of an HTML page, one line per block element. */
function htmlToText(html) {
  let s = String(html || '');
  s = s.replace(/<(script|style|noscript|svg|template)\b[\s\S]*?<\/\1>/gi, ' ');
  s = s.replace(/<(br|\/p|\/div|\/li|\/tr|\/h[1-6]|\/section|\/td|\/th)\b[^>]*>/gi, '\n');
  s = s.replace(/<[^>]+>/g, ' ');
  s = s.replace(/&(?:nbsp|amp|#8377|#x20b9|#39|#x27|quot|lt|gt);/gi, (m) => ENTITIES[m.toLowerCase()] || ' ');
  return s.replace(/[ \t ]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
}

/**
 * Text from <script type="application/ld+json"> blocks (FAQPage Q&A, Product, ...).
 * JS-heavy sites often ship their real content here; a naive crawler that strips all
 * <script> tags throws it away.
 */
function embeddedText(html) {
  const out = [];
  const re = /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(String(html || ''))) !== null) {
    let data;
    try { data = JSON.parse(m[1].trim()); } catch { continue; }
    const stack = [data];
    while (stack.length) {
      const node = stack.pop();
      if (Array.isArray(node)) stack.push(...node);
      else if (node && typeof node === 'object') {
        for (const key of ['name', 'text', 'description']) {
          if (typeof node[key] === 'string') out.push(htmlToText(node[key]));
        }
        stack.push(...Object.values(node));
      }
    }
  }
  return out.join('\n');
}

function count(re, text) { return (text.match(re) || []).length; }

/**
 * Best window after an anchor word, scored by the criteria signals that follow it.
 * Scoring (instead of taking the first match) skips navigation menus such as
 * "Home Loan eligibility", which contain the word but no criteria.
 */
function bestWindow(text, anchor, weights, size = 2500) {
  let best = '';
  let bestScore = 0;
  const re = new RegExp(anchor, 'gi');
  let m;
  while ((m = re.exec(text)) !== null) {
    const win = text.slice(m.index, m.index + size);
    let score = 0;
    let firstSignal = win.length;
    for (const [name, weight] of Object.entries(weights)) {
      score += Math.min(count(SIGNALS[name], win), 3) * weight;
      const at = win.search(new RegExp(SIGNALS[name].source, 'i'));
      if (at >= 0) firstSignal = Math.min(firstSignal, at);
    }
    // A real section has criteria right after its heading; a menu item that merely
    // precedes the section loses a point per 100 chars before the first criterion.
    score -= Math.floor(firstSignal / 100);
    if (score > bestScore) { best = win; bestScore = score; }
  }
  return { text: best, score: bestScore };
}

const ELIGIBILITY_WEIGHTS = { age: 2, money: 2, income: 1, credit: 1, employment: 1 };
const RATE_WEIGHTS = { rate: 2, money: 1 };
const MIN_ELIGIBILITY_SCORE = 6;

/** Both sections for one page. Falls back to the whole text if no section scores. */
function extractSections(html) {
  const text = `${htmlToText(html)}\n${embeddedText(html)}`;
  const elig = bestWindow(text, 'eligib', ELIGIBILITY_WEIGHTS);
  const rates = bestWindow(text, 'interest rate|rate of interest|interest', RATE_WEIGHTS, 1200);
  const found = elig.score >= MIN_ELIGIBILITY_SCORE;
  return {
    // Layout-change resilience: no recognisable section -> give the LLM the start of the page.
    eligibility_text: found ? elig.text : text.slice(0, 4000),
    rates_text: rates.text,
    section_found: found,
    text_chars: text.length,
  };
}

// Exported for `node --test`; inside n8n there is no `module`, so this is skipped.
if (typeof module !== 'undefined') module.exports = { htmlToText, embeddedText, bestWindow, extractSections };
