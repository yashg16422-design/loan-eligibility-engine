-- Workflow A · Crawl health: after "Finish run". Params: $1 run_id, $2 drop threshold (percent).
--
-- A layout change on a lender or comparison site does not fail the crawl: its pages come back
-- `failed` (no eligibility section found) and the old products are kept. This compares usable
-- pages per channel (ok + unchanged + fixture) with the previous crawl and flags a channel that
-- dropped by more than $2 percent or has no usable page at all. A flagged run is stored in
-- workflow_errors (visible in /ops/errors) and alerts at most once per day. No product data
-- is changed here.
WITH this_run AS (
    SELECT channel, count(*) FILTER (WHERE status IN ('ok', 'unchanged', 'fixture')) AS usable,
           count(*) AS pages
    FROM crawl_runs WHERE run_id = $1::uuid AND channel IS NOT NULL GROUP BY channel
), prev_run AS (
    SELECT run_id FROM crawl_runs
    WHERE run_id <> $1::uuid
    GROUP BY run_id
    HAVING max(started_at) < (SELECT min(started_at) FROM crawl_runs WHERE run_id = $1::uuid)
    ORDER BY max(started_at) DESC LIMIT 1
), prev AS (
    SELECT channel, count(*) FILTER (WHERE status IN ('ok', 'unchanged', 'fixture')) AS usable
    FROM crawl_runs WHERE run_id = (SELECT run_id FROM prev_run) AND channel IS NOT NULL
    GROUP BY channel
), cmp AS (
    SELECT coalesce(t.channel, p.channel) AS channel, coalesce(t.usable, 0) AS usable,
           p.usable AS prev_usable
    FROM this_run t FULL JOIN prev p USING (channel)
), bad AS (
    SELECT * FROM cmp
    WHERE usable = 0 OR (prev_usable > 0 AND usable < prev_usable * (1 - $2::numeric / 100))
), summary AS (
    SELECT string_agg(format('%s: %s usable pages (previous crawl %s)', channel, usable,
                             coalesce(prev_usable::text, 'none')), '; ' ORDER BY channel) AS text
    FROM bad
), last_alert AS (
    SELECT max(created_at) AS at FROM workflow_errors WHERE workflow = 'A · crawl health'
), ins AS (
    INSERT INTO workflow_errors (workflow, node, message)
    SELECT 'A · crawl health', 'Crawl health', 'Crawl degraded: ' || (SELECT text FROM summary)
    WHERE EXISTS (SELECT 1 FROM bad)
    RETURNING id
)
SELECT $1::text AS run_id,
       EXISTS (SELECT 1 FROM bad) AS degraded,
       EXISTS (SELECT 1 FROM ins)
         AND coalesce((SELECT at FROM last_alert) < now() - interval '1 day', true) AS should_alert,
       coalesce((SELECT text FROM summary), 'all channels healthy') AS summary,
       (SELECT coalesce(json_agg(cmp ORDER BY channel), '[]'::json) FROM cmp) AS channels;
