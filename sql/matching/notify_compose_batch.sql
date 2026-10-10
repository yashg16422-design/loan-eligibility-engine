-- Workflow C1 · The next batch of users whose real send was skipped (demo cap) and whose email
-- is not composed yet. Params: $1 run_id, $2 batch size.
-- Same picks as an emailed user (best offer per lender, ranked by tier, fit score, rate). A user
-- whose matches were superseded since still gets a row (picks NULL), so the batch settles them.
WITH todo AS (
  SELECT n.user_id FROM notifications n
  WHERE n.run_id = $1::uuid AND n.status = 'skipped_demo' AND n.subject IS NULL
  ORDER BY n.user_id LIMIT $2::int
), new_m AS (
  SELECT m.user_id, m.tier, m.requirements, m.fit_score, m.fit_reasons,
         p.lender, p.lender_key, p.channel, p.product_url, p.product_name,
         p.interest_rate_min, p.interest_rate_max, p.loan_amount_max
  FROM matches m JOIN loan_products p USING (product_id) JOIN todo USING (user_id)
  WHERE m.match_run_id = $1::uuid AND m.status = 'active'
), per_user AS (
  SELECT user_id, count(*)::int AS matches_total, count(DISTINCT lender_key)::int AS lenders_total
  FROM new_m GROUP BY user_id
), best_per_lender AS (
  SELECT DISTINCT ON (n.user_id, n.lender_key) n.*
  FROM new_m n
  ORDER BY n.user_id, n.lender_key, (n.tier = 'eligible') DESC, n.fit_score DESC,
           n.interest_rate_min NULLS LAST, n.product_name
), ranked AS (
  SELECT b.*, row_number() OVER (PARTITION BY b.user_id ORDER BY (b.tier = 'eligible') DESC,
         b.fit_score DESC, b.interest_rate_min NULLS LAST, b.product_name) AS rnk
  FROM best_per_lender b
)
SELECT $1::text AS run_id, u.user_id::text, u.name, u.monthly_income, u.credit_score,
       u.employment_status, u.age, pu.matches_total, pu.lenders_total,
       json_agg(json_build_object(
         'lender', r.lender, 'channel', r.channel, 'tier', r.tier, 'requirements', r.requirements,
         'interest_rate_min', r.interest_rate_min, 'interest_rate_max', r.interest_rate_max,
         'loan_amount_max', r.loan_amount_max, 'product_url', r.product_url,
         'fit_score', r.fit_score, 'fit_reasons', r.fit_reasons) ORDER BY r.rnk)
         FILTER (WHERE r.rnk <= 5) AS picks
FROM todo t
JOIN users u ON u.user_id = t.user_id
LEFT JOIN per_user pu ON pu.user_id = t.user_id
LEFT JOIN ranked r ON r.user_id = t.user_id
GROUP BY u.user_id, pu.matches_total, pu.lenders_total
ORDER BY u.user_id;
