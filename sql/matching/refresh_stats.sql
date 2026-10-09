-- Workflow B · between Stage 1 and Stage 3: refresh planner statistics.
-- Stage 1 just bulk-wrote match_classes/match_pairs and earlier runs wrote matches; with
-- stale statistics Postgres estimated ~26 rows instead of ~272,000 and picked nested-loop
-- joins (a 7-minute Stage 3 in testing). ANALYZE takes about a second and fixes the plan.
-- Allowed for n8n_workflows by GRANT MAINTAIN (PostgreSQL 17) on exactly these tables.
ANALYZE match_classes, match_pairs, matches;
