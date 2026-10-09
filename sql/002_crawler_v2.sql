-- 002_crawler_v2.sql: Workflow A v2 (PLAN.md §10).
--   * crawl_sources: the config table that drives the crawler. Adding, removing or
--     switching a site (static <-> rendered) is a row change, not a workflow edit.
--   * loan_products: which lender (canonical key), which channel, and whether the
--     LLM's criteria passed evidence verification.
--   * crawl_runs: one row per page per run, with richer statuses.

CREATE TABLE crawl_sources (
    source_id    text PRIMARY KEY,
    channel      text NOT NULL CHECK (channel IN ('direct', 'bankbazaar', 'paisabazaar')),
    -- hub   = fetch `url`, follow links matching `link_pattern` (capture group 1 = lender slug)
    -- fixed = `url` is the product page itself (direct lenders, found via their sitemap.xml)
    discovery    text NOT NULL CHECK (discovery IN ('hub', 'fixed')),
    url          text NOT NULL,
    link_pattern text,
    lender_slug  text,
    fetch_mode   text NOT NULL DEFAULT 'static' CHECK (fetch_mode IN ('static', 'rendered')),
    enabled      boolean NOT NULL DEFAULT true,
    notes        text,
    CHECK ((discovery = 'hub') = (link_pattern IS NOT NULL)),
    CHECK ((discovery = 'fixed') = (lender_slug IS NOT NULL))
);

INSERT INTO crawl_sources (source_id, channel, discovery, url, link_pattern, lender_slug, fetch_mode, enabled, notes) VALUES
  ('bankbazaar', 'bankbazaar', 'hub', 'https://www.bankbazaar.com/personal-loan.html',
   '^https://www\.bankbazaar\.com/([a-z0-9-]+)-personal-loan\.html$', NULL, 'static', true,
   '26 lenders discovered from the hub (2026-10-09)'),
  ('paisabazaar', 'paisabazaar', 'hub', 'https://www.paisabazaar.com/personal-loan/',
   '^https://www\.paisabazaar\.com/([a-z0-9-]+)/personal-loan/?$', NULL, 'static', true,
   '~10 lenders discovered from the hub'),
  ('direct:icici', 'direct', 'fixed', 'https://www.icici.bank.in/personal-banking/loans/personal-loan', NULL, 'icici', 'static', true, 'found via sitemap.xml'),
  ('direct:idfc-first', 'direct', 'fixed', 'https://www.idfcfirst.bank.in/personal-banking/loans/personal-loan', NULL, 'idfc-first', 'static', true, 'found via sitemap.xml'),
  ('direct:tata-capital', 'direct', 'fixed', 'https://www.tatacapital.com/personal-loan.html', NULL, 'tata-capital', 'static', true, 'found via sitemap.xml'),
  ('direct:indusind', 'direct', 'fixed', 'https://www.indusind.bank.in/in/en/personal/loans/personal-loan.html', NULL, 'indusind', 'static', true, 'found via sitemap.xml'),
  ('direct:sbi', 'direct', 'fixed', 'https://sbi.bank.in/web/personal-banking/loans/personal-loans/sbi-personal-loan', NULL, 'sbi', 'static', true, 'found via sitemap.xml'),
  ('direct:axis', 'direct', 'fixed', 'https://www.axisbank.com/retail/loans/personal-loan/eligibility', NULL, 'axis', 'rendered', false,
   'criteria load client-side; enable with the optional renderer (site allows plain HTTP)'),
  ('direct:bank-of-baroda', 'direct', 'fixed', 'https://bankofbaroda.bank.in/loans/personal-loan/baroda-personal-loan', NULL, 'bank-of-baroda', 'static', false,
   'DISABLED: site answers bots with 403 (WAF); never bypassed');

ALTER TABLE loan_products
    ADD COLUMN lender_key   text,
    ADD COLUMN channel      text CHECK (channel IN ('direct', 'bankbazaar', 'paisabazaar')),
    ADD COLUMN verification text CHECK (verification IN ('ok', 'ambiguous', 'unverified'));
CREATE INDEX loan_products_source_url_idx ON loan_products (source_url);
CREATE INDEX loan_products_lender_key_idx ON loan_products (lender_key);

-- One row per page per run: the crawl report (what was fetched, how, and what came out).
ALTER TABLE crawl_runs
    ADD COLUMN channel      text,
    ADD COLUMN lender_slug  text,
    ADD COLUMN http_status  int,
    ADD COLUMN changed      boolean,
    ADD COLUMN llm_input_tokens  int,
    ADD COLUMN llm_output_tokens int,
    DROP CONSTRAINT crawl_runs_status_check,
    ADD CONSTRAINT crawl_runs_status_check CHECK (status IN (
        'ok',                -- fetched live, parsed
        'unchanged',         -- fetched live, same criteria hash: zero LLM calls
        'fixture',           -- live fetch failed, parsed the S3 snapshot instead
        'blocked',           -- 403/429/challenge: the site refuses bots, skipped
        'robots_disallowed', -- robots.txt says no, never fetched
        'failed'));          -- nothing usable (live and fixture both failed)
