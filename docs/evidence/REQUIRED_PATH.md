# Evidence: every required path, measured on the live stack (2026-10-10)

Captured 2026-10-10 about 14:35 UTC from the deployed stack in ap-southeast-2. Nothing here is typed by hand:
each block is the output of the command shown, trimmed only to the columns listed. Screenshots of the
same things are in [`docs/screenshots/`](../screenshots/).

| Assignment requirement | Proof below |
|---|---|
| CSV upload UI → S3 → Lambda → RDS (scalable ingestion) | [1](#1-ingestion-csv--s3--lambda--rds) |
| Self-hosted n8n in Docker, workflows A, B, C | [2](#2-n8n-is-running-in-docker-on-ec2), [3](#3-every-workflow-has-run-in-production) |
| Workflow A: daily crawler | [3](#3-every-workflow-has-run-in-production), [4](#4-workflow-a-crawl-results) |
| Workflow B: webhook after ingestion, matching + Treasure Hunt | [3](#3-every-workflow-has-run-in-production), [5](#5-workflow-b--b1-the-match-run-for-that-upload) |
| Workflow C: SES email to test-inbox aliases only | [6](#6-workflow-c-emails-only-to-the-gmail-aliases) |
| Credentials (AWS, database) configured inside n8n | [7](#7-credentials-inside-n8n) |
| Error handling | [8](#8-workflow-e-the-error-path-was-drilled) |
| Code quality: tests in CI | [9](#9-ci) |

## 1. Ingestion: CSV → S3 → Lambda → RDS

The real `users.csv` (10,000 rows) uploaded from the merchant console. The browser sends it straight to S3
with a presigned POST, S3 → SQS → the ingest Lambda validates and upserts it into RDS, then calls the n8n
webhook.

```
$ scripts/psql.sh -c "SELECT job_id, original_filename, status, total_rows, inserted, updated, unchanged, rejected, created_at FROM upload_jobs WHERE job_id = '745637c2-4b70-40a4-b92b-1119e7f5ca1f';"
                job_id                | original_filename |  status   | total_rows | inserted | updated | unchanged | rejected |          created_at
--------------------------------------+-------------------+-----------+------------+----------+---------+-----------+----------+-------------------------------
 745637c2-4b70-40a4-b92b-1119e7f5ca1f | users.csv         | COMPLETED |      10000 |    10000 |       0 |         0 |        0 | 2026-10-10 13:35:35.938922+00
```

Totals in the engine database at capture time (two accounts have each uploaded `users.csv`, so their customers
are stored separately; the other 10 rows are single checks):

```
 users | products | active_products | lenders | matches
-------+----------+-----------------+---------+---------
 20010 |       64 |              58 |      26 |  499574
```

## 2. n8n is running in Docker on EC2

Read through SSM Run Command (no SSH, no open port). n8n keeps its own state in the `n8n` database on the
same private RDS instance.

```
$ cd /opt/n8n && docker compose ps --format "{{.Name}} {{.Image}} {{.Status}}"
n8n-n8n-1 docker.n8n.io/n8nio/n8n:2.42.5 Up 6 hours (healthy)

$ grep DB_ .env     (password line not shown)
DB_TYPE=postgresdb
DB_POSTGRESDB_DATABASE=n8n

$ docker compose exec -T n8n n8n list:workflow
LoanEngineWfB001|B · User-loan matching
LoanEngineWfE001|E · Error handler
LoanEngineWfE101|E1 · Error drill (fails on purpose)
LoanEngineWfC001|C · Notify matched users (SES)
LoanEngineWfA101|A1 · Process page batch (sub-workflow)
LoanEngineWfA001|A · Loan product discovery (crawler)
LoanEngineWfB101|B1 · Match one run (Treasure Hunt)
```

Published (active) state, from n8n's `workflow_entity` table. E1 is the error drill and is off on purpose:

```
                  name                  | active
----------------------------------------+--------
 A1 · Process page batch (sub-workflow) | t
 A · Loan product discovery (crawler)   | t
 B1 · Match one run (Treasure Hunt)     | t
 B · User-loan matching                 | t
 C · Notify matched users (SES)         | t
 E1 · Error drill (fails on purpose)    | f
 E · Error handler                      | t
```

## 3. Every workflow has run in production

n8n's own execution log (`execution_entity` joined to `workflow_entity`), grouped by how each run started.
`trigger` = schedule, `webhook` = called by the ingest Lambda, `integrated` = called by another workflow,
`cli` = started from the command line during setup, `error` = n8n's error-workflow hook.

```
                  name                  | status  |    mode    | executions |  first (UTC)     |  last (UTC)
----------------------------------------+---------+------------+------------+------------------+------------------
 A · Loan product discovery (crawler)   | success | trigger    |          2 | 2026-10-09 00:30 | 2026-10-10 00:30
 A · Loan product discovery (crawler)   | success | cli        |          5 | 2026-10-08 21:51 | 2026-10-09 04:55
 A · Loan product discovery (crawler)   | error   | cli        |          2 | 2026-10-08 21:48 | 2026-10-08 21:49
 A · Loan product discovery (crawler)   | crashed | cli        |          1 | 2026-10-09 20:58 | 2026-10-09 20:58
 A1 · Process page batch (sub-workflow) | success | integrated |         72 | 2026-10-08 21:51 | 2026-10-10 00:30
 B · User-loan matching                 | success | webhook    |         28 | 2026-10-08 22:59 | 2026-10-10 13:46
 B · User-loan matching                 | success | trigger    |        239 | 2026-10-08 22:40 | 2026-10-10 14:30
 B · User-loan matching                 | success | integrated |          2 | 2026-10-09 04:52 | 2026-10-09 04:56
 B · User-loan matching                 | success | cli        |          2 | 2026-10-08 22:38 | 2026-10-09 04:41
 B · User-loan matching                 | crashed | integrated |          1 | 2026-10-09 21:00 | 2026-10-09 21:00
 B1 · Match one run (Treasure Hunt)     | success | integrated |         34 | 2026-10-08 22:38 | 2026-10-10 13:46
 B1 · Match one run (Treasure Hunt)     | crashed | integrated |          1 | 2026-10-09 21:00 | 2026-10-09 21:00
 C · Notify matched users (SES)         | success | integrated |         31 | 2026-10-08 22:59 | 2026-10-10 13:48
 C · Notify matched users (SES)         | success | cli        |          1 | 2026-10-08 22:55 | 2026-10-08 22:55
 E · Error handler                      | success | error      |          1 | 2026-10-09 04:35 | 2026-10-09 04:35
 E · Error handler                      | success | cli        |          1 | 2026-10-09 04:29 | 2026-10-09 04:29
 E1 · Error drill (fails on purpose)    | error   | trigger    |          1 | 2026-10-09 04:35 | 2026-10-09 04:35
 E1 · Error drill (fails on purpose)    | error   | cli        |          1 | 2026-10-09 04:31 | 2026-10-09 04:31
```

How to read it:
- **A runs daily on its schedule**: 00:30 UTC on both days is 06:00 IST, the configured cron.
- **B ran 28 times from the ingest webhook**, once per uploaded file. The 239 `trigger` runs are its 10-minute
  sweeper (about 40 hours of ticks), which picks up a job if a webhook call was ever lost; most find nothing to do.
- **B → B1 → C chain**: 34 B1 match runs and 31 C notification runs, all `integrated`, which means B called them.
  C has no trigger of its own, so it can only run after matching finishes.
- **The 3 `crashed` rows (2026-10-09 ~21:00)** were runs in flight while n8n restarted for a workflow
  re-import. The interrupted run (`55b7ab2b`) was picked up again and finished: all 35 rows in `pipeline_runs`
  are `done`, none stuck.
- **The 2 early `error` runs of A** were on the first evening (2026-10-08), before the crawler was finished.

## 4. Workflow A: crawl results

```
$ scripts/psql.sh -c "SELECT date_trunc('day', started_at)::date AS day, status, count(*) AS sources, sum(products_found) AS products_found FROM crawl_runs GROUP BY 1,2 ORDER BY 1,2;"
    day     |  status   | sources | products_found
------------+-----------+---------+----------------
 2026-10-08 | failed    |       3 |
 2026-10-08 | ok        |      80 |            117
 2026-10-08 | unchanged |      40 |
 2026-10-09 | failed    |      32 |              0
 2026-10-09 | fixture   |       1 |              1
 2026-10-09 | ok        |      63 |            100
 2026-10-09 | unchanged |      68 |
 2026-10-10 | failed    |       1 |
 2026-10-10 | unchanged |      40 |
```

- **`unchanged`** means the page's content hash matched the last crawl, so Nova Pro was not called again
  (README §7, change detection).
- **`failed`** sources are pages that refused or timed out. They are recorded and the other sources go on.
- **On 2026-10-10 the scheduled crawl found every page unchanged**, so it cost no LLM call.

The products are 64 in the table: 58 active, from 26 lenders.

## 5. Workflow B / B1: the match run for that upload

```
$ scripts/psql.sh -c "SELECT run_id, mode, status, users_in, naive_pairs, classes, class_product_pairs, llm_calls, llm_cache_hits, matches_new, correctness_ok, emails_sent, round(extract(epoch FROM finished_at-started_at)::numeric,1) AS seconds FROM pipeline_runs WHERE job_id = '745637c2-4b70-40a4-b92b-1119e7f5ca1f';"
                run_id                |  mode  | status | users_in | naive_pairs | classes | class_product_pairs | llm_calls | llm_cache_hits | matches_new | correctness_ok | emails_sent | seconds
--------------------------------------+--------+--------+----------+-------------+---------+---------------------+-----------+----------------+-------------+----------------+-------------+---------
 ccfff5cb-5ddc-4c13-940a-bd7354c9c4c2 | upload | done   |    10000 |      580000 |     164 |                9512 |         0 |             44 |      249623 | t              |           5 |    39.8
```

- **Classes:** the 580,000 user × product pairs were reduced to 164 equivalence classes, giving 9,512
  class × product decisions.
- **No LLM calls:** every criteria answer came from the cache.
- **Correctness check passed:** the brute-force check of every pair (`correctness_ok`) found no mismatches.
- **Time:** 39.8 s end to end.
- **First run:** the same file's first run (with 5 LLM calls) and the full export are in
  [`pipeline_runs_2026-10-10.json`](pipeline_runs_2026-10-10.json) and this folder's [README](README.md).

## 6. Workflow C: emails only to the Gmail aliases

Every row in `notifications` ever written, grouped by recipient:

```
$ scripts/psql.sh -c "SELECT alias_email, status, count(*) AS emails FROM notifications GROUP BY 1,2 ORDER BY 1,2;"
        alias_email         |    status    | emails
----------------------------+--------------+--------
 (demo cap: not sent)       | skipped_demo |  19990
 yashg16422+one@gmail.com   | sent         |      9
 yashg16422+three@gmail.com | sent         |      7
 yashg16422+two@gmail.com   | sent         |      4
```

For the 10,000-user upload above:

```
    status    | count
--------------+-------
 sent         |     5
 skipped_demo |  9995
```

- **No CSV address was ever emailed.** Every `sent` row goes to one of the three `+alias` test inboxes.
- **The demo cap sends 5 real emails per run.** Every other matched user gets a `skipped_demo` row, so the
  run is complete and auditable without flooding the inbox.
- **SES is in sandbox,** so it can only deliver to verified identities anyway: a second safety net.

The merchant console shows the first three of those emails as they were composed. The panel is "Emails sent
for this upload", under Analytics.

## 7. Credentials inside n8n

From n8n's `credentials_entity` table. Only names and types are shown; the values are encrypted at rest
with n8n's encryption key.

```
          name           |      type
-------------------------+----------------
 AWS n8n role (assume)   | awsAssumeRole
 Ingest webhook secret   | httpHeaderAuth
 RDS app (n8n_workflows) | postgres
```

- **AWS uses Assume Role.** There are no access keys; the EC2 instance role assumes the n8n role with an
  external ID.
- **Postgres connects as the least-privilege `n8n_workflows` role.**
- **The webhook secret is a header credential**, so it never appears in a workflow export.

Setup steps are in README §5.

## 8. Workflow E: the error path was drilled

```
$ scripts/psql.sh -c "SELECT workflow, node, left(message,70) AS message, created_at FROM workflow_errors ORDER BY created_at DESC;"
              workflow               |         node          |                              message                              |          created_at
-------------------------------------+-----------------------+-------------------------------------------------------------------+-------------------------------
 E1 · Error drill (fails on purpose) | Fail on purpose       | E1 drill: deliberate failure to prove the error workflow [line 1] | 2026-10-09 04:35:41.605355+00
 E · drill (simulated)               | Claim job + start run | Drill: simulated failure to test the error path end to end        | 2026-10-09 04:29:35.637009+00
```

E1 failed on its schedule, and n8n's error hook started E 0.35 s later (section 3, mode `error`). E wrote the
row above (its SES alert is rate-limited by the `Alert due?` check). No real failure has been recorded since.

## 9. CI

```
$ gh run view 38056945177 --json jobs,headSha,conclusion
{"sha":"b95ef82","conclusion":"success","jobs":[{"name":"web","conclusion":"success"},{"name":"test","conclusion":"success"},{"name":"dashboard","conclusion":"success"}]}
```

Locally, at the latest commit: 300 Python tests (unit + Postgres integration), 50 n8n Code-node tests, and 19
dashboard tests all pass; `ruff` is clean.

## How these were captured

- **App database:** `scripts/tunnel-rds.sh`, then `scripts/psql.sh` as the `n8n_workflows` role. The
  tunnel was closed afterwards.
- **n8n database and Docker state:** an SSM Run Command on the EC2 host ran `psql` in a throwaway
  `postgres:16` container, reading the connection from n8n's own `.env` so no password left the host.
