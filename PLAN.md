# PLAN.md — Loan Eligibility Engine (SDE Intern Backend take-home)

Final merged plan: brief v1 + patch v2 + review amendments + decisions locked on 2026-10-08.
Priority order for every decision: **(1) every required path works end-to-end → (2) correct and robust → (3) maximum rubric points.**
Source of truth: the assignment text (`docs/ASSIGNMENT.md`) > this plan > the agent's judgement. If they disagree, the assignment wins.

---

## 1. Rubric → where the points come from

| Rubric category (max) | What earns full marks | Plan sections |
|---|---|---|
| n8n Workflow Design & Automation (30) | 3 robust workflows; creative node use for crawling, data handling and logic; **Treasure Hunt** with measured funnel numbers + correctness proof; idempotent and recoverable | §10, §11, §12, §13 |
| Cloud Architecture & Integration (20) | Event-driven ingestion (claim-check); private network; least privilege; secure AWS↔n8n integration; no secrets in code; everything deployed on AWS | §4, §5, §6, §7, §15 |
| Backend Functionality & Code Quality (30) | Correct, idempotent ingestion; clean, modular, typed, well-commented Python; tests + CI | §5, §8, §9, §16, §17 |
| Documentation & Presentation (20) | Clear architecture diagram, step-by-step deploy, **n8n credential configuration**, design decisions, crawling strategy, Treasure Hunt write-up, 5–10 min video | §18, §19 |
| "Public deployment on AWS is a plus" | The whole system runs on AWS; public upload URL in the README; EC2/n8n shown in the video | §4, §18, §19 |

---

## 2. Locked decisions

| Topic | Decision |
|---|---|
| Language | Python 3.12, Lambda architecture **arm64** (see §23, 2026-10-08) |
| Region | **`ap-southeast-2` (Sydney)**: the account's organization SCP denies every other region (see §23, 2026-10-08) |
| Deployment | Everything on AWS. ONE `serverless.yml` (Serverless Framework v4, `serverless login`) deploys all AWS resources: Lambdas + raw CloudFormation for VPC, endpoints, RDS, S3, SQS/DLQ, EC2, IAM, Secrets, alarms |
| n8n | Self-hosted in Docker Compose on EC2 `t3.small`, Amazon Linux 2023, public subnet for **outbound only**. **No inbound from the internet.** Editor reached via SSM Session Manager port-forward to `localhost:5678`. Port 5678 open only to the Lambda security group (webhook). |
| LLM | Amazon Bedrock, **Amazon Nova Pro** (`amazon.nova-pro-v1:0`, in-region in `ap-southeast-2`), temperature 0, Converse API. No Claude (company-details form). |
| Email | SES `ap-southeast-2`, sandbox mode. Sender = my verified Gmail address. Recipients = my verified Gmail `+aliases` only. **No domain** (not required; README notes production would use a verified domain + DKIM). |
| Ingestion | Presigned POST → S3 → SQS standard queue + DLQ → ingest Lambda in the VPC → RDS (claim-check pattern) |
| Matching | SQL equivalence classes → rule stage → LLM only on residual pairs, with cache. Three outcomes: eligible / conditional / not eligible |
| NAT Gateway | None. Private Lambdas need no internet. |
| Cost | Not a constraint ($100 credits). Budget alerts at $20 and $50 anyway. Do not tear down until the result is known. |

---

## 3. Hard requirements checklist (each must be visibly satisfied)

- [ ] Python; AWS Lambda; RDS PostgreSQL; SES. API Gateway optional → we use an HTTP API.
- [ ] Self-hosted n8n in Docker (`docker-compose.yml`). All core business logic orchestrated in n8n.
- [ ] LLM API used for specific AI tasks (Bedrock Nova Pro).
- [ ] `serverless.yml` deploys all required AWS resources.
- [x] FR1: scalable, event-driven bulk CSV upload avoiding API Gateway/Lambda size and timeout limits; parsed and stored in a dedicated RDS table.
- [ ] Workflow A: schedule trigger (daily); crawl 2–3 public lender sites; extract `product_name`, `interest_rate`, eligibility criteria; store in `loan_products`.
- [ ] Workflow B: webhook trigger after a CSV is processed; fetch new users; fetch all products; matching logic in n8n; store in `matches` (`user_id` ↔ `product_id`); multi-stage optimized pipeline (Treasure Hunt).
- [ ] Workflow C: runs after B completes; personalized email per user with new matches; sent with the n8n **AWS SES node**; only to my Gmail `+aliases`, never to CSV addresses.
- [x] Minimal UI for CSV upload (pipeline entry point). (2026-10-09: live; 10k rows COMPLETED in ~10 s)
- [ ] Private GitHub repo; collaborators invited: `ujjwalkala-clickpe`, `HarshSrivastav-Dailype`, `ManishBiswal-clickpe`, `tushar-clickpe`.
- [ ] Repo contains `serverless.yml`, `docker-compose.yml`, and a JSON export of every n8n workflow.
- [ ] README: architecture diagram; step-by-step deploy; **how to configure credentials inside n8n (AWS + database)**; design decisions; crawling strategy; Treasure Hunt solution.
- [ ] Video 5–10 min: node-by-node walkthrough, live end-to-end run, email received in the test inbox.
- [ ] Submit repo + video links via the form within 72 h.

---

## 4. Architecture

### 4.1 Network
- VPC `10.0.0.0/16`, 2 AZs (an RDS subnet group needs ≥2 AZs).
- Public subnets ×2 + Internet Gateway: EC2 (n8n) with an auto-assigned public IPv4 for outbound traffic only. No Elastic IP.
- Private subnets ×2: RDS + all Lambdas.
- **S3 gateway endpoint** (free) on the private route table.
- **Secrets Manager interface endpoint** in the private subnets, private DNS on, its SG allows 443 from the Lambda SG.
- No NAT Gateway.

### 4.2 Security groups
| SG | Inbound |
|---|---|
| `lambda-sg` | none |
| `ec2-n8n-sg` | 5678 from `lambda-sg` only. No 22, no 80/443. |
| `rds-sg` | 5432 from `lambda-sg` and `ec2-n8n-sg` |
| `endpoint-sg` | 443 from `lambda-sg` and `ec2-n8n-sg` (see §23) |

### 4.3 Components
| Component | Purpose |
|---|---|
| HTTP API (API Gateway v2) | `GET /` (UI), `POST /uploads`, `GET /uploads/{job_id}`; default route throttling (e.g. rate 10, burst 20) |
| `api` Lambda (VPC) | Serves the UI HTML, creates upload jobs + presigned POSTs, returns job status |
| S3 data bucket | `raw/` uploads; `fixtures/` crawler snapshots; `config/` n8n deploy files |
| SQS `ingest-queue` + `ingest-dlq` | S3 `ObjectCreated` events; `maxReceiveCount` 3 |
| `ingest` Lambda (VPC) | Streams, validates, loads the CSV; calls the n8n webhook |
| `dlq-handler` Lambda (VPC) | Marks jobs FAILED when ingest crashed hard (timeout/OOM) |
| `migrate` Lambda (VPC) | Applies `sql/` migrations, creates DB roles and grants; invoked once via `serverless invoke` |
| RDS PostgreSQL 16 | `app` database (engine data) + `n8n` database (n8n's own storage) |
| EC2 + n8n | Workflows A, B, C + error workflow; calls Bedrock, SES, lender sites |
| Bedrock (Nova Pro) | Criteria extraction (A) + residual eligibility judgement (B) |
| SES | Notification emails (C) |
| CloudWatch + SNS + Budgets | Alarms and cost alerts |

### 4.4 End-to-end flow
UI → `POST /uploads` → presigned POST → browser uploads the file to S3 → S3 event → SQS → ingest Lambda → RDS commit → webhook (private IP) → n8n Workflow B → Workflow C → SES → Gmail alias.
Daily: Workflow A (schedule) → `loan_products` → Workflow B in product mode → C.

---

## 5. FR1 — Scalable user data ingestion

### 5.1 API
- `POST /uploads` → inserts `upload_jobs` (`status = AWAITING_UPLOAD`, `attempts = 0`) and returns a presigned POST:
  - key pinned to exactly `raw/{job_id}.csv`
  - `Content-Type` = `text/csv` (the UI sets this form field explicitly; browsers may otherwise send `application/vnd.ms-excel`)
  - `content-length-range` 1 B – 50 MB
  - expiry 600 s
  - Presigning is local signing (no network call).
- `GET /uploads/{job_id}` → status (+ derived states), counts, first 20 rejects, and match/notify progress (from `pipeline_runs` / `notifications`) for the UI tracker.
- Derived states (computed by the API, never stored):
  - `EXPIRED`: `status = AWAITING_UPLOAD` AND `attempts = 0` AND `created_at` older than 15 min (the file never arrived).
  - `RETRYING`: `status = AWAITING_UPLOAD` AND `attempts > 0`.

### 5.2 S3 + SQS
- Bucket: Block Public Access ON, SSE-S3, CORS allowing POST only from the API origin, lifecycle rule deleting `raw/` after 7 days.
- Notification: `s3:ObjectCreated:*` filtered to prefix `raw/` and suffix `.csv` → **standard** SQS (FIFO is not a direct S3 notification target).
- Queue policy: allow `s3.amazonaws.com` with `aws:SourceArn` = bucket and `aws:SourceAccount` = account.
- DLQ with `maxReceiveCount` 3.
- Event source mapping: `batchSize` 1, `maximumConcurrency` 2 (the minimum allowed). No reserved concurrency.
- Ingest Lambda: timeout **120 s**, memory 512 MB. Queue visibility timeout **720 s** (≥ 6× the function timeout).

### 5.3 Ingest Lambda algorithm
1. If the message is `s3:TestEvent` → return success.
2. **Loop over every record** in the S3 event. For each record:
   - URL-decode the key with plus handling.
   - Require the exact pattern `^raw/<uuid>\.csv$` and parse + validate the `job_id`.
   - On mismatch: log and skip. Never touch the database with an unvalidated id.
3. Short transaction: `attempts = attempts + 1` **only where `status = AWAITING_UPLOAD`** (duplicates for finished jobs don't inflate it).
4. Main transaction (all or nothing):
   1. `SELECT … FOR UPDATE SKIP LOCKED` where `job_id = $1 AND status = 'AWAITING_UPLOAD'`. No row → duplicate or in-flight delivery → return success.
   2. Set `PROCESSING`. This is invisible outside the transaction, so the UI shows "uploaded / queued" until done. Documented trade-off.
   3. Stream the CSV from S3 (`utf-8-sig` for the BOM, CRLF-safe). Match the header **by name**.
   4. Missing required column → set `FAILED` + error, commit, no webhook.
   5. Validate rows (§9). Bad rows → `upload_rejects`.
   6. Duplicate `user_id` within the file: last occurrence wins; earlier ones rejected as `duplicate_in_file`. **Dedupe before COPY.**
   7. `COPY` valid rows into a **TEMP table** (`ON COMMIT DROP`). Never a shared staging table.
   8. Upsert into `users`, updating only when values differ (`IS DISTINCT FROM`). `upload_job_id` is set to this job **only for inserted or changed rows**. Unchanged users don't need re-matching.
   9. Counts: inserted / updated / unchanged / rejected. Set `COMPLETED`, `completed_at`. COMMIT.
5. On exception: if the SQS `ApproximateReceiveCount` ≥ 3 → set `FAILED` + error text in a **separate** transaction and return success (message deleted). Otherwise re-raise (SQS redelivers after 720 s).
6. After a `COMPLETED` commit: POST `{job_id}` to `http://<n8n-private-ip>:5678/webhook/ingest-complete` with a header-auth secret, 3 retries with backoff (1 s, 2 s, 4 s). If all fail → log it; Workflow B's sweeper picks the job up within 10 min.

### 5.4 dlq-handler Lambda
- Trigger: the DLQ, batch size 1. Covers hard crashes where no handler code ran (timeout/OOM).
- Parse and validate the `job_id` the same way. If the job is still `AWAITING_UPLOAD` → set `FAILED`, error `"ingest crashed (timeout/OOM)"`.
- The CloudWatch alarm on DLQ depth stays.

### 5.5 Libraries
- `psycopg[binary]` v3 (COPY support). Install for the Lambda platform (manylinux aarch64 / arm64, Python 3.12). **Smoke-test the import on the first deploy.** Fallback: pure-Python `pg8000`.
- AWS Lambda Powertools Logger, with `job_id` as the correlation id.
- Secrets: Lambdas read their DB secret from Secrets Manager at cold start (via the interface endpoint) and cache it.

### 5.6 Documented trade-offs (README)
- At 10k rows (~1 MB, seconds), S3 → Lambda directly would also work. SQS is kept for retries, the DLQ, and concurrency control that protects RDS connections.
- For files above ~1 GB: S3 byte-range chunking → one SQS message per chunk, or Step Functions Distributed Map. README only; not built.

---

## 6. n8n host (EC2)

- `t3.small`, Amazon Linux 2023, IMDSv2 required, encrypted 20 GB gp3, public subnet (outbound only), no SSH.
- Instance role:
  - `AmazonSSMManagedInstanceCore`
  - `secretsmanager:GetSecretValue` on the n8n secrets only
  - `ses:SendEmail`, `ses:SendRawEmail`
  - `bedrock:InvokeModel` on Nova Pro (model and/or inference profile ARN)
  - `s3:GetObject` on `config/*` and `fixtures/*`
- Boot (user-data, no secrets inside it):
  1. Install Docker + the Compose plugin.
  2. Pull `docker-compose.yml` from `s3://<bucket>/config/`.
  3. Read secrets via the instance role → write `.env` (chmod 600).
  4. `docker compose up -d`.
- Updates: `scripts/n8n-sync.sh` uploads config to S3 and runs an SSM Run Command to pull + restart. No instance replacement needed.
- Debug: `/var/log/cloud-init-output.log`.

### 6.1 docker-compose.yml
- `n8n` service with a **pinned version tag** (not `latest`), `restart: unless-stopped`, port 5678, volume for `/home/node/.n8n`.
- Profile `local`: adds a `postgres:16` container and points n8n at it, so a reviewer can run n8n locally and import the workflow JSONs without AWS.

### 6.2 n8n environment
| Variable | Value / reason |
|---|---|
| `DB_TYPE` | `postgresdb` (n8n data in the RDS `n8n` database → survives instance rebuilds) |
| `DB_POSTGRESDB_HOST/PORT/DATABASE/USER/PASSWORD` | RDS endpoint, 5432, `n8n`, `n8n_meta`, from the secret |
| `DB_POSTGRESDB_SSL_ENABLED` | `true` (RDS PG ≥15 forces SSL) |
| `DB_POSTGRESDB_SSL_REJECT_UNAUTHORIZED` | `false`, or mount the RDS CA bundle (preferred if time) |
| `N8N_ENCRYPTION_KEY` | Generated once, stored in Secrets Manager. Without the same key a rebuilt instance cannot decrypt stored credentials. |
| `WEBHOOK_URL` | `http://<private-ip>:5678/` |
| `N8N_PROTOCOL` | `http` |
| `N8N_SECURE_COOKIE` | `false` — the editor is only reached through the SSM tunnel at `http://localhost`; no public exposure |
| `GENERIC_TIMEZONE`, `TZ` | `Asia/Kolkata` |
| `N8N_DIAGNOSTICS_ENABLED` | `false` |
| `EXECUTIONS_TIMEOUT` | `600` (must stay below the 15-min lock reclaim, §11.2) |
| `EXECUTIONS_TIMEOUT_MAX` | `900` |

Version-specific settings (e.g. task runners for Code nodes) must be checked against the docs for the pinned version.

### 6.3 n8n credentials (README "Configuring credentials inside n8n" section, with screenshots)
1. **Postgres:** host = RDS endpoint, database `app`, user `n8n_workflows`, SSL require.
2. **AWS:** used by the SES node and the Bedrock node. Try the instance-role ("system credentials" / Assume Role) option first. **Fallback:** an IAM user whose only permissions are `ses:SendEmail`, `ses:SendRawEmail` and `bedrock:InvokeModel` on Nova Pro. Verify on Day 2 (§22).
3. **Header Auth:** the webhook secret (same value the ingest Lambda sends).

### 6.4 Access from my laptop (macOS)
- Prerequisites: AWS CLI v2 + Session Manager plugin.
- `scripts/tunnel-n8n.sh`: SSM port-forward to EC2 port 5678 → open `http://localhost:5678`.
- `scripts/tunnel-rds.sh`: SSM port-forward through the EC2 instance to RDS 5432 (`AWS-StartPortForwardingSessionToRemoteHost`) → `psql` from the Mac.

---

## 7. RDS + database roles

- PostgreSQL 16, `db.t4g.micro`, single-AZ, 20 GB gp3, encrypted, private, 1-day backups, SSL forced.
- Master password managed by RDS in Secrets Manager (rotates every 7 days by default). **Used only by the migrate Lambda**, fetched per invocation, never cached.
- App role passwords: CloudFormation `AWS::SecretsManager::Secret` with `GenerateSecretString`, no automatic rotation (README: production would add a rotation Lambda). The migrate Lambda reads them and creates the roles.

| Role | Used by | Grants |
|---|---|---|
| master | migrate Lambda | everything (migrations only) |
| `app_ingest` | api, ingest, dlq-handler Lambdas | SELECT/INSERT/UPDATE on `upload_jobs`, `users`, `upload_rejects`; SELECT on `pipeline_runs`, `notifications` (UI tracker); TEMP on database `app`; USAGE on needed sequences |
| `n8n_workflows` | n8n Postgres credential | SELECT `users`; SELECT `upload_jobs` + UPDATE (`match_status`, `match_started_at`, `matched_at`) only; SELECT/INSERT/UPDATE on `loan_products`, `matches`, `llm_decisions`, `pipeline_runs`, `notifications`, `crawl_runs`, `workflow_errors`; USAGE on sequences; TEMP |
| `n8n_meta` | n8n internal storage | owner of database `n8n` only |

The README includes this least-privilege table.

---

## 8. Data model (database `app`)

**upload_jobs**: `job_id` UUID PK, `s3_key`, `original_filename`, `status` (AWAITING_UPLOAD | PROCESSING | COMPLETED | FAILED), `attempts` INT, `total_rows`, `inserted`, `updated`, `unchanged`, `rejected`, `error`, `created_at`, `completed_at`, `match_status` (NULL | RUNNING | DONE | FAILED), `match_started_at`, `matched_at`. Indexes: `status`, `match_status`.

**users**: `user_id` UUID PK, `name` TEXT NULL, `email` TEXT NOT NULL, `monthly_income` INT, `credit_score` INT, `employment_status` TEXT, `age` INT, `upload_job_id` UUID FK, `created_at`, `updated_at`. CHECK constraints per §9. Indexes: `upload_job_id`, `email`. **No UNIQUE on email** (the sample has repeated name/email with different `user_id`s).

**upload_rejects**: id PK, `job_id` FK, `row_number`, `raw_line`, `reason`. Index: `job_id`.

**loan_products**: `product_id` UUID PK, `lender`, `source_url`, `product_name`, `product_url`, `interest_rate_min` / `interest_rate_max` NUMERIC(5,2) (% p.a.), `rate_type` (reducing | flat | unknown), `min_monthly_income` INT NULL, `min_credit_score` / `max_credit_score` INT NULL, `min_age` / `max_age` INT NULL, `employment_types` TEXT[] NULL (NULL = all), `loan_amount_min` / `loan_amount_max` BIGINT NULL, `tenure_months_max` INT NULL, `other_criteria_text` TEXT NULL, `raw_extracted` JSONB (raw strings from the LLM), `criteria_json` JSONB (normalized), `criteria_hash`, `is_active`, `first_seen_at`, `last_seen_at`, `last_changed_at`. UNIQUE(`source_url`, `product_name`).

**crawl_runs**: `run_id`, `source_url`, `status` (ok | failed | fixture), `products_found`, `error`, `started_at`, `finished_at`. PK(`run_id`, `source_url`).

**matches**: `match_id` PK, `user_id` FK, `product_id` FK, `job_id` NULL, `match_run_id`, `tier` (eligible | conditional), `requirements` TEXT NULL, `stage_decided` (sql | rules | llm), `llm_reason`, `status` (active | superseded), `created_at`, `superseded_at`, `notified_at`.
- Partial unique index on (`user_id`, `product_id`) WHERE `status = 'active'`.
- Partial index for C: (`user_id`) WHERE `status = 'active' AND notified_at IS NULL`.
- A tier change on an active pair → update `tier`/`requirements` in place and keep `notified_at`.
- A pair superseded and later eligible again → a new active row → emailed again (intentional: the user re-qualified; documented).

**llm_decisions** (cache): `criteria_hash`, `class_signature`, `prompt_version`, `tier` (eligible | conditional | not_eligible), `requirements`, `reason`, `model_id`, `created_at`. PK(`criteria_hash`, `class_signature`, `prompt_version`).

**pipeline_runs** (Treasure Hunt evidence): `run_id` UUID PK, `mode` (upload | products), `job_id` NULL, `status`, `started_at`, `finished_at`, `users_in`, `products_in`, `naive_pairs`, `pairs_after_sql`, `classes`, `class_product_pairs`, `rule_decided`, `llm_candidates`, `llm_cache_hits`, `llm_calls`, `llm_input_tokens`, `llm_output_tokens`, `llm_cost_usd_est`, `matches_new`, `matches_superseded`, `matches_unchanged`, `emails_sent`, `emails_skipped_demo`, `emails_failed`.

**notifications**: id PK, `user_id`, `alias_email`, `job_id`, `run_id`, `status` (sent | skipped_demo | failed), `ses_message_id`, `error`, `created_at`.

**workflow_errors**: id PK, `workflow`, `node`, `message`, `execution_id`, `created_at`.

---

## 9. Validation rules (from the real `users.csv`: 10,000 rows)

Observed: columns `user_id, name, email, monthly_income, credit_score, employment_status, age`; UUID ids; `@example.com` emails; income ~₹27k–139k/month; scores ~650–800; employment values `Salaried`, `Self-Employed`, `Business`; ages ~22–50; repeated name+email with different `user_id`s.

| Field | Rule |
|---|---|
| `user_id` | Valid UUID; in-file duplicates → last wins, earlier rows rejected |
| `name` | Optional; trimmed |
| `email` | Required; trimmed, lowercased, basic format check |
| `monthly_income` | Integer > 0 (rupees/month) |
| `credit_score` | Integer 300–900 (CIBIL) |
| `employment_status` | Case-insensitive, trimmed map: `salaried` → salaried; `self-employed` / `self employed` / `self_employed` → self_employed; `business` / `business owner` → business; anything else rejected |
| `age` | Integer 18–100 |
| File level | Header by name; BOM; CRLF; missing required column → job FAILED with a clear error |

Before coding, run a quick profile of the full file (duplicates, ranges, distinct employment labels) and adjust if it shows anything new.

**Measured profile (2026-10-08, `data/users.csv`):** 10,000 rows, 0 blanks, 0 stray spaces, no BOM, **CRLF line endings**, all lowercase UUIDs, 0 duplicate `user_id`s. Emails: 2,632 distinct, 2,403 reused (up to 12×), all `@example.com`. `monthly_income` 25,000–150,000 (multiples of 1,000, 126 distinct, median 87,000). `credit_score` 650–800 (31 distinct, steps of 5). `age` 22–50. Employment: Salaried 3,389 / Self-Employed 3,371 / Business 3,240. Exact `(income, score, age, employment)` duplicates: 9,869 distinct profiles out of 10,000, so deduping identical profiles saves only 1.3%; the Treasure Hunt needs threshold-derived classes (§11.4). The §9 rules stay as written; the file is clean, and the rejection rules are exercised with hand-made test fixtures.

---

## 10. Workflow A — Loan Product Discovery (crawler)

**Triggers:** Schedule (daily 06:00 IST) + Manual trigger (for the demo).

**Source selection (Day 1, before building A):** test candidate lender pages **from an AWS IP** (CloudShell in `ap-southeast-2`, or the EC2 instance once it's up), not only from the laptop. Pick 2–3 pages that:
- render eligibility criteria in server-side HTML,
- are allowed by `robots.txt`,
- show numeric criteria.

Never bypass CAPTCHAs or bot protection. Save an HTML snapshot of each to `s3://<bucket>/fixtures/` as the fallback.

**Per source** (Loop Over Items):
1. HTTP Request: browser-like User-Agent, 20 s timeout, 3 retries.
   - On failure → load the S3 fixture, `crawl_runs.status = fixture`.
   - If the fixture is also missing → `failed`.
2. HTML node: CSS selectors (per-source config) → product blocks + criteria text.
3. Code node: whitespace-normalize the extracted criteria text → `criteria_hash` per product (**never hash the whole page**).
4. Postgres: compare with the stored `criteria_hash`. Unchanged → only touch `last_seen_at` (zero LLM calls).
5. New/changed → Bedrock Nova Pro (temperature 0, versioned prompt in `n8n/prompts/`). It extracts **raw strings** per field into a strict JSON schema.
   - **Rule: the LLM extracts, the code does the math.**
   - `null` means "not stated", never 0.
6. Code node — validate the schema + deterministic normalizer (unit-tested in Python, with an identical JS port in the Code node):
   - Income → monthly rupees:
     - "₹X lakh p.a." → X×100000/12
     - "₹X per annum" → X/12
     - "₹X/month" → X
     - "₹Xk" → X×1000
     - Commas stripped; round to integer.
   - Interest → min/max % p.a., plus `rate_type` if stated.
   - Condition-dependent thresholds (e.g. "₹25k, ₹30k in metro cities") → the **most permissive** value goes into the hard filter; the condition text goes into `other_criteria_text` (feeds the "conditional" tier).
   - NULL criterion = "lender stated no limit" → passes.
   - Keep the original strings in `raw_extracted` for audit.
7. Postgres: upsert `loan_products`; write `crawl_runs`.

**After all sources:**
- Deactivate products not seen in this run **only for sources with `status = ok`**.
- A source returning 0 products when it previously had >0 is treated as `failed` (likely a layout change) → nothing deactivated.
- Active matches of deactivated products → `superseded` (no email).
- If any product is new, changed, or deactivated → Execute Workflow B with `{mode: "products", product_ids: [...]}`.

**Where the LLM runs here:** once per new/changed product, not per user. This moves the LLM upstream and is the first lever of the Treasure Hunt.

---

## 11. Workflow B — Matching + Optimization Treasure Hunt

### 11.1 Triggers
1. **Webhook** `POST /webhook/ingest-complete`, header auth, respond immediately, body `{job_id}` (primary, required).
2. **Schedule** every 10 min (sweeper): picks up to 5 jobs matching the lock predicate below. Recovers from "n8n was down at upload time".
3. **Execute Workflow trigger** from A: `{mode: "products", product_ids}`.

### 11.2 Lock (upload mode)
`UPDATE upload_jobs SET match_status='RUNNING', match_started_at=now() WHERE job_id=$1 AND status='COMPLETED' AND (match_status IS NULL OR (match_status='RUNNING' AND match_started_at < now() - interval '15 minutes')) RETURNING job_id` → 0 rows → exit.
`EXECUTIONS_TIMEOUT` (600 s) < the 15-min reclaim, so a live run is never reclaimed.

### 11.3 Scope
- Upload mode: users with `upload_job_id = job_id` × all active products.
- Product mode: all users × `product_ids`.
- Insert a `pipeline_runs` row (`mode`, `job_id`).

### 11.4 Stage 1 — SQL hard filter with exact equivalence classes (n8n Postgres node)
- Collect every distinct threshold from in-scope active products: income mins, score bounds, age bounds, employment sets, **plus any numeric threshold used by Stage 2 rules** (e.g. age at maturity). Everything must be a cut point, so classes stay exact.
- Cut each user's fields at exactly those thresholds → `class_signature` = (income interval, score interval, age interval, employment).
- **Never use fixed bands**: users at 26k and 45k could differ for a 30k product.
- Users in the same class have identical outcomes for every numeric/categorical criterion → exact, no false positives.
- Apply the hard criteria (NULL passes) at class level → passing (`class_signature`, `product_id`) pairs + user count per class.
- Record `naive_pairs` (users × products), `pairs_after_sql` (sum of users over passing pairs), `classes`, `class_product_pairs`.
- Report the **measured** class count (expected tens to a few hundred); never quote an estimate.

### 11.5 Stage 2 — rule engine (n8n Code node)
- Rules SQL can't express cleanly (age at maturity = age + tenure ≤ max age; employment sub-rules from `criteria_json`).
- Products with empty `other_criteria_text` → decided here as `eligible`.
- Products with residual free-text criteria → `llm_candidate`.

### 11.6 Stage 3 — LLM on residual pairs only (Bedrock Nova Pro)
- Cache lookup first: `llm_decisions` by (`criteria_hash`, `class_signature`, `prompt_version`).
- Cache misses → batch about 20 class-product pairs per call; temperature 0; strict JSON array output `[{pair_id, tier, requirements, reason}]`; schema-validated; retried on failure.
- The input describes the class as ranges (e.g. "income ₹30,000–49,999/month, score 700–749, salaried, age 25–34") plus the product's `other_criteria_text`.
- Three tiers:
  - **eligible**: all criteria checkable from our 5 fields and met.
  - **conditional**: all checkable criteria met, but some can't be checked (e.g. "2 years work experience", "metro city", "salary account") → listed in `requirements`.
  - **not_eligible**: a checkable criterion fails.
- On LLM failure: **fail open** → `conditional` with `requirements` = the raw criteria text, reason `needs_review`. The pipeline never blocks.
- Write results to the cache (re-runs cost ~0 calls). Record tokens from the Bedrock response usage plus an estimated cost in `pipeline_runs`.

### 11.7 Stage 4 — expand classes to users + match diff (one Postgres query in **transaction mode**)
- Take `pg_advisory_xact_lock(<constant>)` first: serializes concurrent upload-mode and product-mode writes.
- Expand passing classes (eligible + conditional) to the in-scope users → the new set.
- Diff against active matches in the same scope:
  - New pairs → insert active (`ON CONFLICT` on the partial unique index `DO NOTHING`).
  - Tier/requirements changed → update in place.
  - Active pairs not in the new set → `superseded`.
- Record `matches_new` / `superseded` / `unchanged`.

### 11.8 Stage 5 — finish
- Complete the `pipeline_runs` counts.
- Upload mode → `match_status = DONE`, `matched_at`. On error → `FAILED`.
- Execute Workflow C with `{run_id}`.

### 11.9 Correctness proof
`sql/brute_force_check.sql` does the naive per-user join on the hard criteria and compares it with the Stage 1+2 decisions. It must be identical (same count, same pairs). Run it in tests and show the result in the README and video.

**Treasure Hunt write-up (README):** funnel table from the real `pipeline_runs` row:
`naive_pairs → pairs_after_sql → classes → class_product_pairs → llm_candidates → llm_cache_hits → llm_calls → matches_new`
plus tokens/cost, plus the correctness proof, plus a second run showing cache hits ≈ 100%.

---

## 12. Workflow C — Notification

1. Trigger: Execute Workflow trigger `{run_id}`.
2. Postgres: active matches with `notified_at IS NULL` and `match_run_id = run_id`, joined to products. Rank per user: eligible before conditional, then `interest_rate_min` ascending.
3. Aggregate **per user** (the assignment says "for each user").
4. Deterministic user order. The first `DEMO_MAX_EMAILS` (n8n variable, default 5) are sent. The rest → `notifications.status = skipped_demo`, `notified_at` set (simulated delivery, logged as "would send", documented).
5. Code node: personalized HTML + text email:
   - greeting by name,
   - per product: lender, product name, rate range, tier badge, "you'll also need: …" requirements, link,
   - footer: "indicative eligibility, not a loan offer".
6. Recipient = `ALIASES[hash(user_id) mod N]` (verified `+aliases`). **Guard:** the recipient must be in the configured alias list, otherwise abort. Never the CSV email.
7. **AWS SES node** send (From = verified Gmail) → Wait 1 s between sends (sandbox: 1 msg/s, 200/24 h).
8. Write `notifications` (sent with `ses_message_id` / failed with error); set `notified_at` for sent; update the `pipeline_runs` email counts.

Deliverability: a Gmail sender via SES will likely land in Spam (gmail.com DMARC is quarantine). Before recording, open the first test email and mark it "Not spam".

---

## 13. Error handling + observability

- n8n **Error workflow** (set as the error workflow on A, B, C): Error Trigger → insert `workflow_errors` → SES email to an alias.
- CloudWatch alarms → SNS topic → email subscription (my Gmail; confirm the subscription):
  - DLQ `ApproximateNumberOfMessagesVisible` > 0
  - ingest Lambda `Errors` > 0
  - dlq-handler invocations > 0
- AWS Budgets: $20 and $50.
- Lambda log retention 14 days; structured JSON logs with `job_id`.

---

## 14. UI (served by `GET /` from the api Lambda; same origin as the API → no API CORS)

- Single HTML file, vanilla JS, no build step, accessible labels.
- File picker → client-side checks (`.csv`, ≤ 50 MB) → `POST /uploads` → multipart POST to S3 with the presigned fields (explicit `Content-Type: text/csv`).
- Polls `GET /uploads/{job_id}` every 2 s. Pipeline tracker: **Uploaded → Ingested** (inserted / updated / unchanged / rejected) **→ Matched** (funnel numbers) **→ Notified** (sent / skipped).
- Shows EXPIRED / RETRYING / FAILED clearly; rejects table (first 20).

---

## 15. Security summary (README section)

- No inbound internet access to n8n, RDS, or the Lambdas. The public surface is only the HTTP API (throttled) and S3 presigned POSTs (key-pinned, size-capped, 10-min expiry).
- Private RDS, SSL forced, least-privilege roles (§7).
- Secrets only in Secrets Manager. Nothing in code, user-data, or the n8n workflow exports.
- Webhook: private network + header-auth secret.
- IAM: per-function roles, scoped to specific ARNs; EC2 role scoped to SES, Bedrock (Nova Pro), its secrets, and S3 prefixes.
- S3: Block Public Access, SSE-S3, lifecycle deletion of raw PII after 7 days.
- Emails are never sent to CSV addresses (alias guard + SES sandbox as a second guard).

---

## 16. Repo layout + code quality

```
serverless.yml            docker-compose.yml        README.md
PLAN.md                   CLAUDE.md                 .env.example
requirements.txt          requirements-dev.txt      pyproject.toml (ruff, pytest)
docs/ASSIGNMENT.md        docs/architecture.drawio  docs/architecture.png  docs/screenshots/
loan_engine/common/   db.py secrets.py validation.py normalize.py s3_stream.py jobs.py s3_keys.py logging.py
loan_engine/api/      handler.py ui.html
loan_engine/ingest/   handler.py
loan_engine/dlq_handler/ handler.py
loan_engine/migrate/  handler.py
sql/          001_schema.sql R__grants.sql brute_force_check.sql
n8n/workflows/ A_loan_discovery.json B_matching.json C_notification.json error_handler.json
n8n/prompts/  extract_criteria_v1.md judge_eligibility_v1.md
scripts/      deploy.sh n8n-sync.sh tunnel-n8n.sh tunnel-rds.sh upload-sample.sh
tests/unit/   tests/integration/
.github/workflows/ci.yml
```

- Type hints, docstrings, small pure functions (validation/normalization separate from I/O), comments explaining **why**.
- ruff (lint + format) and pytest in CI (GitHub Actions) on push; badge in the README.
- `.env.example` only. Before committing workflow JSONs, check that they contain no credential secrets.

---

## 17. Tests

**Unit (pytest):**
- Validator: BOM, CRLF, header order, missing column, duplicate `user_id` (last wins), out-of-range values, bad employment label, bad email.
- S3 key parser: spaces, plus signs, URL-encoding, non-UUID keys, wrong prefix.
- Multi-record S3 event handling; `s3:TestEvent` ignored.
- Derived states: EXPIRED (attempts 0, >15 min) vs RETRYING (attempts >0).
- Normalizer: lakh p.a., per annum, /month, k, commas, ranges, "not stated" → None.
- Equivalence classes: classes vs brute force on synthetic products (identical outcomes).

**Integration (`tests/integration/`, against the deployed stack):**
- Upload a 50-row CSV via the API → poll until COMPLETED → counts correct.
- Same file again → idempotent (no new inserts, no new matches, no emails).
- Re-upload with a lower income → superseded pair, no email.
- Poison path: forced exception on attempt 3 → FAILED; simulated timeout → dlq-handler → FAILED.
- n8n stopped during upload → sweeper matches the job within 10 min after restart.
- Concurrent upload-mode + product-mode runs → no duplicate active pairs.
- `brute_force_check.sql` = optimized result on the 10k file.

---

## 18. README outline

1. Overview + **Live deployment** (public upload URL, region; n8n runs on EC2 inside the VPC, deliberately reachable only via SSM for security).
2. Architecture: draw.io diagram with AWS icons (PNG) + Mermaid sequence diagram of the event flow.
3. Design decisions + why: claim-check ingestion, private network, endpoints instead of NAT, single-transaction ingest, idempotency, poison handling, least privilege.
4. Deploy step by step: prerequisites (AWS CLI v2, Session Manager plugin, Serverless v4 login, Python 3.12), SES identity verification, Bedrock model check, deploy order, migrate, n8n boot, tunnels, importing workflows.
5. **Configuring credentials inside n8n** (Postgres, AWS, Header Auth), with screenshots.
6. Workflows A/B/C node by node + **web crawling strategy** (source selection criteria, criteria hashing, fixtures, deactivation rules, robots.txt respect).
7. **Optimization Treasure Hunt:** funnel table with real numbers, cost/tokens, cache-hit run, correctness proof.
8. Failure handling matrix (duplicate event, bad CSV, poison job, n8n down, LLM down, site down/layout change).
9. Security (§15) + least-privilege table.
10. Trade-offs / production next steps: SES production access + own domain/DKIM, public n8n behind ALB + ACM, Multi-AZ RDS, secret rotation, chunked ingestion for >1 GB, crawler layout-change alerts, Cognito auth on uploads.
11. Cost notes.

---

## 19. Video script (~8 min)

| Time | Content |
|---|---|
| 0:00 | Architecture diagram (45 s) |
| 0:45 | AWS console: stack resources + EC2 running (10 s) → n8n editor via the tunnel (10 s) |
| 1:05 | Upload a small CSV in the UI; tracker moves through every stage; rejects shown (1 min) |
| 2:05 | Workflow A node by node (1.5 min) |
| 3:35 | Workflow B node by node + funnel numbers from the 10k-row run + correctness check (2.5 min) |
| 6:05 | Workflow C node by node (1 min) |
| 7:05 | Email arriving in the Gmail alias inbox (30 s) |
| 7:35 | Robustness: same file again (idempotent); n8n stopped → sweeper recovers; DLQ alarm (45 s) |
| 8:20 | Wrap-up |

Use a small CSV for the live run so it finishes on camera.

---

## 20. 72-hour build order

**Day 1 — foundation + ingestion**
1. Setup: `serverless login`, budgets, SES identities (sender Gmail + 2–3 `+aliases`), Bedrock Nova Pro playground test (done: `amazon.nova-pro-v1:0` in `ap-southeast-2`, §22), add `docs/ASSIGNMENT.md`.
2. Crawl feasibility from an AWS IP (CloudShell `ap-southeast-2`); pick 2–3 sources; save fixtures.
3. Profile `users.csv`; finalize §9.
4. `serverless.yml` incrementally: network + endpoints → RDS (start early; it takes ~10 min) → S3/SQS/DLQ → Lambdas (migrate, api, ingest, dlq-handler) → EC2.
5. Migrations + roles; UI; end-to-end with the 10k file; unit tests.

**Day 2 — n8n**

6. EC2 boot + n8n env + tunnels; credentials in n8n (write the README section as you go, with screenshots).
7. Workflow A → B (Stages 1–5, funnel, brute-force check) → C → error workflow.

**Day 3 — proof + polish**

8. Integration/failure tests, CI, alarms check.
9. README, diagrams, workflow JSON exports, private repo + 4 collaborators.
10. Record the video, submit. Keep ≥6 h buffer. Do not tear anything down.

---

## 21. Risk register (likelihood × impact)

| # | Risk | Mitigation |
|---|---|---|
| 1 | Lender pages block AWS IPs or render via JS → A empty | Day-1 test from CloudShell/EC2, server-rendered sources only, S3 fixtures, honest README note |
| 2 | Job lifecycle holes (poison, abandoned tickets, lost webhook) | Single-transaction claim, attempts + derived states, poison handling, dlq-handler, sweeper |
| 3 | n8n first boot (SSL, encryption key, cookie, webhook URL) | All env vars set from the start (§6.2); cloud-init log |
| 4 | n8n AWS nodes don't accept the instance-role credential | Scoped IAM user fallback (§6.3) |
| 5 | Compiled deps built for the wrong platform | arm64 Lambdas + manylinux aarch64 wheels (native on the Mac); import smoke test; pg8000 fallback |
| 6 | Wrong matches from banding | Threshold-derived classes + brute-force check |
| 7 | Stale/duplicate matches, concurrent runs | Match status lifecycle + partial unique index + advisory xact lock |
| 8 | LLM failure / throttling | Cache, batching, fail-open `conditional` / `needs_review` |
| 9 | Emails to Spam / sandbox quota / duplicates | "Not spam" before recording, 1 msg/s, demo cap, `notified_at`, alias guard |
| 10 | Credential rotation breaks consumers | Master only for migrations; app roles non-rotating (documented) |
| 11 | Deploy churn (RDS rollback, VPC Lambda ENI teardown, silent user-data failure) | Incremental deploys; cloud-init log; never tear down near the deadline |
| 12 | Hash churn re-runs the LLM; one site down wipes its products | Hash extracted criteria only; deactivate only for `ok` sources |

---

## 22. Fact status

**Checked against official docs/sources on 2026-10-08:**
- SES sandbox: verified recipients only; 200 msgs/24 h; 1 msg/s; per region.
- SQS event source `maximumConcurrency`: min 2, max 1000; supported in serverless.yml.
- SQS visibility timeout ≥ 6× function timeout (AWS recommendation).
- S3 sends `s3:TestEvent`; FIFO SQS is not a direct S3 notification target.
- RDS PostgreSQL ≥15: `rds.force_ssl` defaults to 1.
- n8n DB env vars incl. `DB_POSTGRESDB_SSL_ENABLED`; HTTP needs `N8N_SECURE_COOKIE=false`.
- Serverless Framework v4: free under $2M revenue; requires login or a license key.
- Bedrock serverless models are enabled by default (Oct 2025); only Anthropic models need the one-time form.
- AWS promotional credits cannot pay for Route 53 domain registration.
- gmail.com DMARC moved to quarantine (Feb 2024) → Gmail-sender mail via SES likely lands in Spam.
- Public IPv4: $0.005/hr per address.

**Verified on this account (CLI, 2026-10-08):**
- Organization SCP denies `ap-south-1`, `ap-southeast-1`, `us-east-1` (explicit deny). `ap-southeast-2` allows RDS, Lambda, EC2, Secrets Manager, CloudFormation, SSM, SQS, S3, API Gateway v2, Budgets, IAM, SNS.
- SES `ap-southeast-2`: sandbox, 200 msgs/24 h, 1 msg/s, status HEALTHY.
- Bedrock `ap-southeast-2`: `amazon.nova-pro-v1:0` (in-region) and `apac.amazon.nova-pro-v1:0` (profile) both answer the Converse API, and the response includes `usage.inputTokens/outputTokens`.
- Serverless v4 packages Python natively (`custom.pythonRequirements`, no plugin). `pipCmdExtraArgs` `--platform=manylinux2014_aarch64 --only-binary=:all:` produced `_psycopg.cpython-312-aarch64-linux-gnu.so`; the migrate Lambda imported psycopg 3.2.10 and ran against RDS (2026-10-09). This closes the §5.5 smoke test.
- RDS PG 16.15: the master (`dbadmin`) could `GRANT n8n_meta TO dbadmin` and `CREATE DATABASE n8n OWNER n8n_meta`.

**Must verify during the build (do not assume):**
- Whether n8n's AWS SES node and Bedrock node accept the instance-role / system-credentials AWS credential (and any env flag that needs).
- Version-specific n8n settings for the pinned n8n version (task runners, Postgres node transaction mode).
- CloudShell availability in `ap-southeast-2` (else use the EC2 instance for the crawl test).
- Exact API Gateway / Lambda payload and timeout numbers if quoted in the README (cite docs).

---

## 23. Decision log
(Append here whenever reality forces a change: date, decision, reason, sections affected.)

| Date | Decision | Reason | Sections affected |
|---|---|---|---|
| 2026-10-08 | Region `ap-south-1` → **`ap-southeast-2` (Sydney)** for everything (Lambda, RDS, SES, Bedrock, EC2) | The account belongs to an AWS Organization whose SCP explicitly denies `ap-south-1`, `ap-southeast-1` and `us-east-1`; only Sydney works. Consequences: (a) crawl source testing must be done from a Sydney AWS IP, and Indian lender sites may geo-block it → the S3 fixtures fallback matters more; (b) README notes that production must run in `ap-south-1`, because RBI's Digital Lending Guidelines require borrower data to be stored in India (to verify and cite before quoting). | §2, §10, §12, §22, README |
| 2026-10-08 | Lambda architecture x86_64 → **arm64** | The dev laptop is an Apple Silicon Mac; arm64 builds `psycopg[binary]` natively (manylinux aarch64 wheels), avoids wrong-platform packages (risk #5), and is cheaper per GB-second | §2, §5.5, §21 |
| 2026-10-08 | Dev machine = **macOS (zsh)**, not WSL | Aloo works on a Mac; command blocks are labelled "Mac laptop" | CLAUDE.md, §6.4 |
| 2026-10-08 | Bedrock model id = **`amazon.nova-pro-v1:0` in-region** (not the `apac.` profile) | Tested: both work. In-region keeps data in one region and the IAM policy needs only one model ARN | §2, §6 |
| 2026-10-08 | `endpoint-sg` allows 443 from **`ec2-n8n-sg` too** (not only `lambda-sg`) | With `PrivateDnsEnabled`, every host in the VPC, including the n8n EC2, resolves Secrets Manager to the interface endpoint; otherwise the EC2 boot script couldn't read its secrets | §4.2 |
| 2026-10-08 | Python code lives in a top-level package **`loan_engine/`** (`loan_engine/common`, `loan_engine/ingest`, …) instead of `src/` | Lambda puts only the zip root (`/var/task`) on `sys.path`, so `from loan_engine.common import …` works the same in Lambda and pytest (`pythonpath = ["."]`) with no path hacks | §16 |
| 2026-10-09 | Grants live in a **repeatable** `sql/R__grants.sql`, re-applied on every migrate run; numbered `NNN_*.sql` files run once (tracked in `schema_migrations`). Roles are created in Python because their passwords come from Secrets Manager | New tables can never be left without grants, and no password ever sits in a .sql file. Replaces `002_roles_grants.sql` from §16 | §7, §16 |
| 2026-10-09 | Per-function IAM roles are plain CloudFormation `AWS::IAM::Role` resources referenced with `functions.<fn>.role` | `provider.iam` gives every function one shared role; explicit roles give each Lambda only its own ARNs, with no plugin needed | §15 |
| 2026-10-09 | **Pluggable seams** (Aloo's request): validation rules = `ValidationRules`, overridable via the `VALIDATION_RULES` env JSON (bounded by the DB CHECKs); next-stage trigger = `Notifier` protocol (`N8nWebhookNotifier` / `NoopNotifier`, picked by `N8N_WEBHOOK_URL`); all ingest SQL in `loan_engine/ingest/repository.py` | Business logic can change after real-world feedback without touching the infrastructure; each seam has its own tests | §5, §9 |
| 2026-10-09 | A file-level problem (missing column, **not UTF-8**) fails the job immediately without SQS retries; only other errors are retried | Retrying can't fix a bad file; it would only delay the user's FAILED status by 3×720 s | §5.3 |
| 2026-10-09 | Deploy with the full `serverless deploy`, not `serverless deploy function` | With custom per-function roles, `deploy function` uploads the code but then errors ("Role resource missing RoleName property") on the config step | §20 |
