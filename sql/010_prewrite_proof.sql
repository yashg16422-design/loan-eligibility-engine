-- 010_prewrite_proof.sql: the correctness proof also runs BEFORE any match is written.
--
-- Workflow B1 now checks the class decisions (expanded to users) against a naive per-user
-- evaluation between Stage 1+2 and Stage 3. If they differ, the run stops with zero writes to
-- `matches`; the existing post-write proof still runs after Stage 3. Additive: NULL on older runs.
ALTER TABLE pipeline_runs ADD COLUMN prewrite_ok boolean;
