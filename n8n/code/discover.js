/**
 * Page discovery for Workflow A (PLAN.md §10.1), pure functions.
 *
 * - hub sources: follow links on the hub page that match the source's `link_pattern`
 *   (capture group 1 = lender slug); drop slugs that are site sections, not lenders.
 * - fixed sources: the configured product page (found earlier via the bank's sitemap.xml).
 * - Pages are interleaved round-robin across channels, so consecutive requests go to
 *   different sites (politeness without long sleeps).
 */

// Slugs that match a lender-URL shape but are tools, articles or site sections.
const NOT_A_LENDER = /(^|-)(how|track|apply|instant|online|best|top|for|calculator|status|customer|care|preclosure|interest|emi|eligibility|documents|pre-approved|bad|cibil|apps?|loan|category|reviews?|hindi|tamil|telugu|marathi|blog|news)(-|$)/;

/** Absolute URL for an href on `base` (no URL-resolution edge cases needed for these hubs). */
function absolute(href, base) {
  if (/^https?:\/\//i.test(href)) return href;
  const origin = base.match(/^https?:\/\/[^/]+/i)[0];
  return href.startsWith('/') ? origin + href : null;
}

/** Lender pages linked from a hub page: [{ lender_slug, url }], deduplicated by slug. */
function linksFromHub(html, hubUrl, linkPattern) {
  const pattern = new RegExp(linkPattern);
  const bySlug = new Map();
  const hrefs = String(html || '').match(/href="([^"#?]+)"/g) || [];
  for (const attr of hrefs) {
    const url = absolute(attr.slice(6, -1), hubUrl);
    if (!url) continue;
    const m = pattern.exec(url);
    if (!m || NOT_A_LENDER.test(m[1])) continue;
    // Paisabazaar redirects to the trailing-slash form: request that directly.
    const canonical = url.includes('paisabazaar.com') && !url.endsWith('/') ? `${url}/` : url;
    if (!bySlug.has(m[1])) bySlug.set(m[1], canonical);
  }
  return [...bySlug.entries()].sort().map(([lender_slug, url]) => ({ lender_slug, url }));
}

/** Interleave pages across channels: a,b,c,a,b,c,... (stable within each channel). */
function roundRobin(pages) {
  const queues = new Map();
  for (const p of pages) {
    if (!queues.has(p.channel)) queues.set(p.channel, []);
    queues.get(p.channel).push(p);
  }
  const out = [];
  const lists = [...queues.values()];
  for (let i = 0; out.length < pages.length; i += 1) {
    for (const list of lists) if (i < list.length) out.push(list[i]);
  }
  return out;
}

/**
 * All pages for this run. `hubHtml` maps source_id -> hub HTML (absent if the hub
 * failed). Each page: { source_id, channel, lender_slug, url, fetch_mode }.
 */
function planPages(sources, hubHtml) {
  const pages = [];
  for (const s of sources) {
    if (s.discovery === 'fixed') {
      pages.push({ source_id: s.source_id, channel: s.channel, lender_slug: s.lender_slug, url: s.url, fetch_mode: s.fetch_mode });
    } else if (hubHtml[s.source_id]) {
      for (const link of linksFromHub(hubHtml[s.source_id], s.url, s.link_pattern)) {
        pages.push({ source_id: s.source_id, channel: s.channel, fetch_mode: s.fetch_mode, ...link });
      }
    }
  }
  return roundRobin(pages);
}

if (typeof module !== 'undefined') module.exports = { NOT_A_LENDER, linksFromHub, roundRobin, planPages };
