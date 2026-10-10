-- Workflow C · Users to email. Params: $1 run_id, $2 demo cap (emails per run).
-- New, un-notified active matches of this run. The demo-capped first N users get their
-- top picks: best offer PER LENDER (best platform), ranked by tier, fit score, rate.
WITH new_m AS (
  SELECT m.user_id, m.tier, m.requirements, m.fit_score, m.fit_reasons,
         p.lender, p.lender_key, p.channel, p.product_url, p.product_name,
         p.interest_rate_min, p.interest_rate_max, p.loan_amount_max
  FROM matches m JOIN loan_products p USING (product_id)
  WHERE m.match_run_id = $1::uuid AND m.status = 'active' AND m.notified_at IS NULL
), per_user AS (
  SELECT user_id, count(*)::int AS matches_total, count(DISTINCT lender_key)::int AS lenders_total
  FROM new_m GROUP BY user_id
), chosen AS (
  -- The demo cap counts emails ALREADY sent for this run, so a re-run after a crash sends
  -- only the remainder (each send is recorded the moment SES accepts it).
  SELECT user_id FROM per_user ORDER BY user_id
  LIMIT greatest($2::int - (SELECT count(*) FROM notifications
                            WHERE run_id = $1::uuid AND status = 'sent'), 0)
), best_per_lender AS (
  SELECT DISTINCT ON (n.user_id, n.lender_key) n.*
  FROM new_m n JOIN chosen USING (user_id)
  ORDER BY n.user_id, n.lender_key, (n.tier = 'eligible') DESC, n.fit_score DESC,
           n.interest_rate_min NULLS LAST, n.product_name
), ranked AS (
  SELECT b.*, row_number() OVER (PARTITION BY b.user_id ORDER BY (b.tier = 'eligible') DESC,
         b.fit_score DESC, b.interest_rate_min NULLS LAST, b.product_name) AS rnk
  FROM best_per_lender b
)
SELECT $1::text AS run_id, u.user_id::text, u.name, u.monthly_income, u.credit_score, u.employment_status, u.age,
       pu.matches_total, pu.lenders_total,
       json_agg(json_build_object(
         'lender', r.lender, 'channel', r.channel, 'tier', r.tier, 'requirements', r.requirements,
         'interest_rate_min', r.interest_rate_min, 'interest_rate_max', r.interest_rate_max,
         'loan_amount_max', r.loan_amount_max, 'product_url', r.product_url,
         'fit_score', r.fit_score, 'fit_reasons', r.fit_reasons) ORDER BY r.rnk)
         FILTER (WHERE r.rnk <= 5) AS picks
FROM ranked r JOIN users u USING (user_id) JOIN per_user pu USING (user_id)
GROUP BY u.user_id, pu.matches_total, pu.lenders_total
ORDER BY u.user_id
