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

- [x] Python; AWS Lambda; RDS PostgreSQL; SES. API Gateway optional → we use an HTTP API.
- [x] Self-hosted n8n in Docker (`docker-compose.yml`). All core business logic orchestrated in n8n.
- [x] LLM API used for specific AI tasks (Bedrock Nova Pro).
- [x] `serverless.yml` deploys all required AWS resources.
- [x] FR1: scalable, event-driven bulk CSV upload avoiding API Gateway/Lambda size and timeout limits; parsed and stored in a dedicated RDS table.
- [x] Workflow A: schedule trigger (daily); crawl 2–3 public lender sites; extract `product_name`, `interest_rate`, eligibility criteria; store in `loan_products`. (2026-10-09: 3 channels, 40 pages, 59 products, 26 lenders; daily schedule published)
- [x] Workflow B: webhook trigger after a CSV is processed; fetch new users; fetch all products; matching logic in n8n; store in `matches` (`user_id` ↔ `product_id`); multi-stage optimized pipeline (Treasure Hunt).
- [x] Workflow C: runs after B completes; personalized email per user with new matches; sent with the n8n **AWS SES node**; only to my Gmail `+aliases`, never to CSV addresses.
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

## 10. Workflow A: Loan Product Discovery (crawler), v2 (2026-10-09)

**Triggers:** Schedule (daily 06:00 IST) + Manual trigger (for the demo).

### 10.1 Channels and discovery (verified 2026-10-09 from the EC2's Sydney IP; same results as an Indian IP)
| Channel | Discovery | Lenders | Fetch |
|---|---|---|---|
| Direct lender sites | each bank's `sitemap.xml` (banks moved to `*.bank.in`) | ICICI, IDFC FIRST, Tata Capital, IndusInd, SBI (static); Bank of Baroda, Axis (rendered) | static / rendered |
| BankBazaar | hub `personal-loan.html` → links `<lender>-personal-loan.html` | 26 (per-employment age, min income, work experience, city lists) | static |
| Paisabazaar | hub `/personal-loan/` → links `/<lender>/personal-loan/` | ~18 (rates, CIBIL guidance) | static |

Excluded, with reasons logged in `crawl_runs`: HDFC and Kotak direct (robots.txt disallow, respected); Federal (renders empty in a headless browser, treated as a bot wall and not bypassed); Bajaj's details page (no eligibility content); Policybazaar (no personal-loan products; that group's loans are on Paisabazaar).

### 10.2 Pipeline (per page, streamed)
1. **robots.txt gate** for every URL (skip if disallowed).
2. **Fetch** per the source's `fetch` flag: `static` = n8n HTTP Request (browser UA, 20 s timeout, 3 retries); `rendered` = POST `http://renderer:3000/render` (headless Chromium, §10.4). On failure → S3 fixture → `crawl_runs.status = fixture`.
3. **Isolate the eligibility section**: score every "eligib…" window by the criteria signals that follow it (ages, ₹, years, income, CIBIL) and take the best, so navigation menus are never chosen. If none scores → whole cleaned text (layout-change resilience). Pure function, tested in Python, identical JS in the Code node.
4. **Hash** the isolated text → unchanged = touch `last_seen_at` only (zero LLM calls).
5. **Extract (batched)**: changed sections go to Nova Pro, ~5 per call, strict JSON array keyed by page id, **per employment type**, raw strings only. Schema failure → retry that item alone.
6. **Normalize** (Code node + Python tests): money → monthly ₹, age bands, rates; NULL = not stated; condition text → `other_criteria_text`.
7. **Upsert** one product per **lender × channel × employment type**; per-field provenance in `raw_extracted`.
8. Channels run **in parallel** (Execute Workflow, wait = off); pages are sequential within a site (polite ~1 req / 2 s). Each page writes its products as soon as it is processed (streaming), and each page gets its own `crawl_runs` row.
9. At the end: deactivate only for channels with status ok; then Execute Workflow B (product mode) once, with the new/changed product ids.

### 10.3 Lender normalization
`HDFC` = `HDFC Bank` = `hdfc-bank` → canonical lender key (alias map, pure + tested). Used for "best offer per lender" in emails.

### 10.4 Renderer (the `fetch: rendered` crawler)
`renderer/`: python:3.12-slim + playwright 1.63.0 + headless Chromium shell only (1.28 GB image). Built on the EC2 by `boot.sh`, no published port (only n8n reaches it), `mem_limit` 900m, 2 GB swap on the host. A fresh browser context per request, images/fonts/media blocked, scroll + settle for lazy content, hidden accordion text included. **SSRF guard** (`url_safety.py`, unit-tested): only public http(s); every navigation hop is re-checked, so 169.254.169.254, private and loopback addresses are refused. Bot challenges are reported (`challenge: true`) and never bypassed.

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
| 2026-10-09 | RDS PostgreSQL **16.15 → 17.11** (in-place major upgrade, approved by Aloo) | n8n 2.42.5 logs "Postgres 16 is outside the supported range and receives compatibility support only. Upgrade to Postgres 17 or newer." Done on Day 1 while the data is re-uploadable and before n8n stores anything | §2, §7 |
| 2026-10-09 | n8n pinned to **2.42.5** (stable on 2026-10-08); EC2 **t4g.small arm64** with a pinned AMI; Docker Compose v5.5.1 installed with a SHA-256 check; IMDS hop limit 2 | 2.x renamed `latest`→`stable`; arm64 is cheaper and matches the Mac, where the same image was smoke-tested; a pinned AMI prevents silent instance replacement; hop limit 2 lets the container use the instance role | §6 |
| 2026-10-09 | n8n's AWS access = **"AWS (Assume Role)" credential with System Credentials** → assumes `N8nAwsRole` (SES send + Nova Pro invoke only); needs `N8N_AWS_SYSTEM_CREDENTIALS_ACCESS_ENABLED=true`. **Unverified for the SES node**; fallback = scoped IAM user (§6.3) | The plain "AWS (IAM)" credential only takes access keys; Assume Role avoids long-lived keys | §6.3 |
| 2026-10-09 | n8n verifies the RDS certificate (`DB_POSTGRESDB_SSL_CA_FILE` = the AWS regional trust bundle) instead of `REJECT_UNAUTHORIZED=false` | Real TLS verification at little extra cost | §6.2 |
| 2026-10-09 | `N8nAwsRole` trust policy also requires `sts:ExternalId = loan-engine-dev-n8n` | n8n's AWS (Assume Role) form makes External ID mandatory; enforcing it in the trust policy adds AWS's confused-deputy check on top of the principal-ARN condition | §6.3 |
| 2026-10-09 | **Crawler v2**: 3 channels (direct banks via sitemaps, BankBazaar, Paisabazaar), products = lender × channel × employment type, streamed per page, channels in parallel, batched LLM extraction | Aloo: more vendors and "different platforms show different benefits"; a richer product set (~80) makes the Treasure Hunt classes meaningful. Policybazaar has no PL products → dropped | §10 |
| 2026-10-09 | **Both fetchers**: static HTTP + a headless renderer service (Playwright 1.63.0) behind a per-source `fetch` flag | Unlocks JS-rendered banks (Bank of Baroda 0 KB → 30 KB of text). Isolated container, SSRF-guarded, no public port, no bot-wall bypassing | §10.4, §15 |
| 2026-10-09 | Renderer image built with plain `docker build` on the EC2 | Compose v5 `build` needs buildx ≥ 0.17; AL2023 ships 0.12 | §6 |
| 2026-10-09 | Emails show **Best pick + Top picks (≤1 per lender) + Conditional** via a deterministic, tested ranking (tier → rate → fewest conditions → max amount), not the LLM | Explainable and reproducible; the LLM stays only where judgement is needed | §12 |
| 2026-10-09 | Workflow A's Code-node logic lives in `n8n/code/*.js`: the same file is pasted into n8n and unit-tested with `node --test` (the bottom block runs only when `$input` exists) | One source of truth, so there is no Python→JS port to drift; what is tested is what runs | §10, §16, §17 |
| 2026-10-09 | Prompt **v2** + **evidence verification**: every criteria entry quotes evidence; each sentence fragment must appear verbatim on the page and contain the extracted numbers, and the quote must not name another employment type. Failing entries become *conditional* (never a hard filter) | Live test: v1 swapped IIFL's age bands. v2 + verification catches model errors (IIFL) while accepting stitched-but-genuine quotes (HDFC); 5/8 entries verified on a 5-page sample; the rest fail safe | §10.2, §11.6 |
| 2026-10-09 | Renderer **off by default** (compose profile `renderer`, `ENABLE_RENDERER=true` to opt in). Hard rule: 403/429/challenge = skip, never retry with a browser. Bank of Baroda dropped (WAF 403) | Aloo prefers not to depend on a headless browser; embedded ld+json covers most JS-heavy pages; the 403 rule keeps us out of bot-wall territory | §10.4 |
| 2026-10-09 | Measured inventory: **40 usable pages / 45** (BankBazaar 25, Paisabazaar 10, direct 5), ~28 lenders, ~80 products. Fixtures in `s3://…/fixtures/` | Replaces estimates with measured numbers (`docs/crawl_inventory.json`) | §10.1 |
| 2026-10-09 | Workflow JSON is **generated** by `n8n/build_workflows.py` from the tested `n8n/code/*.js` + the prompt `.md`, imported with `scripts/n8n-workflows.sh import` (n8n CLI over SSM), then reviewed node by node in the UI | Keeps the running workflow identical to the tested code; a hand-built 38-node workflow would drift. Deviation from "build in the UI" in CLAUDE.md, agreed with Aloo for speed + consistency | §16, CLAUDE.md |
| 2026-10-09 | A = parent (discovery, robots, batching) + **A1 sub-workflow** (one batch of ≤5 pages). Both must be **published** (n8n 2.x: called sub-workflows must be published; publishing A also arms its daily schedule) | Linear loop in the parent, free branching in the child; n8n 2.x requirement found live ("Workflow is not active") | §10.2 |
| 2026-10-09 | Page hash = SHA-256(`prompt=v2;normalizer=2` + sections). Bumping either version re-processes every page once | Measured: run 2 (normalizer fix) re-processed 40/40 pages; run 3 (no change) 0 LLM tokens, 35 s vs 87 s | §10.2 |
| 2026-10-09 | Normalizer v2: several age bands → most permissive + full text kept as a condition; turnover/ITR/profit are never a monthly-income filter (become conditions); a "monthly" value > ₹10 lakh is treated as annual | Live data: ICICI self-employed was stored as age 25–28 and ₹15 lakh/month; the LLM's extraction was correct, the parser was wrong | §10.2 |
| 2026-10-09 | No `URL` global in Code nodes (n8n 2.x task-runner sandbox) → regex helpers + a test that runs every module with `URL` removed | Found live: "URL is not defined" | §10 |
| 2026-10-09 | Treasure Hunt v2: the LLM **compiles** each product's free-text criteria into checkable rules once (cached by text hash + prompt version) instead of judging (class × product) pairs; rule thresholds become class cut points; `ANALYZE` between Stage 1 and Stage 3 (PG17 `GRANT MAINTAIN`) | Pair-level judging would need ~180 calls (~15 min > n8n's 10-min limit). Measured on RDS: 590,000 naive pairs → 164 classes → 5 LLM calls once ($0.024), then 0; brute-force proof 0 mismatches; 40 s. Stale stats made Stage 3 take 7+ min in testing | §11 |
| 2026-10-09 | C emails the top 5 per user (best offer per lender), demo cap of 5 real emails per run, rest `skipped_demo`; all loop results are collapsed to ONE item before the summary query | Live bug: a Postgres node runs once per input item, so the summary ran 5× (duplicated rows); fixed and the data cleaned once with the admin role | §12 |
| 2026-10-09 | **Error workflow E** (Error Trigger → `errors.js` → `workflow_errors` → SES alert, rate-limited to 1/workflow/30 min) set as `settings.errorWorkflow` of A, A1, B, B1, C; **E1 drill** (schedule that fails on purpose, published only during `scripts/n8n-workflows.sh drill`) | Found live: an `n8n execute` (CLI) failure does NOT start the error workflow (short-lived process), so the drill uses a real scheduled execution inside the server. Verified: E1 execution 89 → `workflow_errors` row + alert | §16, §17 |
| 2026-10-09 | **CI** (GitHub Actions): ruff, `node --test`, pytest incl. integration on a Postgres 17 container with TLS, and "committed workflow JSON == generator output" (`DATA_BUCKET` env lets the generator run without AWS). Plus a **workflow lint** test (connections, orphans, errorWorkflow, sub-workflow ids, webhook auth, credential refs, secret patterns, Code-node syntax), mutation-checked | Evidence of quality on every push; a reviewer (human or LLM) can trust the exports without importing them | §18 |
| 2026-10-09 | B hardening: webhook `job_id` validated as UUID; re-claim closes the abandoned run; sweeper closes runs `running` > 30 min. A → B **product mode** wired (changed product ids after each crawl). Stage 1 stores an empty cut list as `[]`, not JSON `null` | The new product-mode integration test failed on the `null` cut list ("cannot extract elements from a scalar"): it would have broken the first live A → B call | §11, §16 |
| 2026-10-09 | **Tried and reverted: schema-forced LLM output** (Converse `toolChoice.tool` + JSON Schema, supported by Nova per the user guide). Kept: a shared defensive parser (`structured.js`: fences/prose tolerated, placeholder strings such as "null" normalized to null) and a fix for the compile prompt's head (it included the `{{#each texts}}` template) | Measured: single page = identical values (input tokens 667 → 1,352); but a forced tool is called ONCE and Nova put only 1–2 of 5 pages in the batch array (reproduced locally; live crawl: 19 of 25 pages failed safe, kept their old products). Text mode: 5/5, 40/40 on the full crawl. Batched completeness beats a shape guarantee; the quote verification stays the truth check | §10.2, §11 |
| 2026-10-09 | **Extra: borrower dashboard + engine console** at `/app` on the existing api Lambda (no CloudFront, no CORS). `POST /check` writes a 1-row CSV to `raw/`, so a visitor takes the bulk-upload path end to end (measured ≈ 11 s); HMAC tokens (key in Secrets Manager); `user_preferences` + `upload_jobs.source` (migration 004, additive); `/ops/*` aggregates only. The client what-if simulator mirrors Stage 1+2 and is tested against Workflow B's live decisions on all 59 products | Shows the pipeline's output from the borrower's and operator's side while touching no matching code; the landing page is built separately by a cloud session that links to `/app` | §12, README §14 |
| 2026-10-09 | Email → dashboard: Workflow C calls `POST /internal/email-tokens` once per run (guarded by the existing webhook secret, constant-time compare) and each email gets a signed 14-day "View all N matches" link; https-only, escaped; failure-tolerant (email without link) | Keeps the HMAC key in AWS (no env access opened in n8n Code nodes, no secret in workflow exports); verified live end to end | §12, README §14 |
| 2026-10-10 | **Final integration:** the landing (`web/`, from the cloud session's `ui` branch) is served at `/` by the api Lambda (`GET /{proxy+}` for its assets; more specific routes win), the app at `/app/`, the minimal uploader kept at `/upload`. The app adopts the landing's tokens exactly (true black, hairline boxes, glacier/coral/amber/violet as meaning, Inter + JetBrains Mono, no decorative motion). Overview is assignment-first (bulk upload + live A→B→C + CSV analytics + Workflows A/B/C/E); results ordered Top 5 → eligible → may qualify → not eligible (exact rule) → tips | Owner's direction: one product, assignment asks at the top, no AI-slop motion, clean dropdowns |
| 2026-10-10 | **Accounts on Amazon Cognito** (email + password, email-code verification via COGNITO_DEFAULT, which reaches any address unlike our sandboxed SES); API Gateway JWT authorizer on `/account/*` (intrinsics in `issuerUrl`/`audience` work in Serverless v4, verified on deploy); `accounts` + `account_profiles` (migration 005, first saver owns a check). Passwordless email OTP was rejected: it requires SES out of the sandbox (Cognito docs) | Real user database with auth emails delivered to the user directly, before the stateful freeze; user pool `DeletionPolicy: Retain` + deletion protection |
| 2026-10-10 | No separate dlq-handler Lambda (planned in §5.4): the ingest handler marks a job FAILED and consumes the message on its 3rd attempt; only hard crashes reach the DLQ, which now raises a CloudWatch alarm (plus alarms on ingest and api Lambda errors) to the operator via SNS email | One fewer function; poison handling lives where the failure is understood; the audit (DF8) found the old README sentence overstated the DLQ path |
| 2026-10-10 | **External audit fixes (AUDIT.md, commit c0bc9ae):** DF7 listed conditions are checked against the page (normalizer v3); unverified ones go after a marker that compile.js never compiles, so invented text cannot reject anyone. DF9 the brute-force proof gates B1 (IF → stop before Finish run, so C is never called) and a "Treasure Hunt funnel" node outputs the funnel. DF6 sweeper/claim moved to `sql/matching/{sweeper,claim}.sql`; FAILED jobs retried ≤ 3 times, 10 min apart. DF11 Stage 3 supersedes only users classified in this run. DF10 email tokens only for users with un-notified matches; 50 uploads/day cap. DF8 CloudWatch alarms (DLQ, Lambda errors) via SNS; README DLQ wording corrected. DF13 evidence export in `docs/evidence/`. DF4/DF5 deploy order and credential ids documented/configurable. Header spelling variants normalized | Each defect verified in the code before fixing; each fix has a test (integration where SQL changed). The workflow-lint test caught a duplicate `const` the DF7 change introduced in a pasted Code node before it shipped |
| 2026-10-11 | **Data reset without touching accounts:** `DELETE /me` (a person deletes their own instant check), `DELETE /account/profiles[/{id}]` (an account clears its saved checks; bulk-upload profiles are only unlinked), `DELETE /uploads[/{job_id}]` (Cognito `admin` group: one upload's users or every CSV user, so a file can be re-run as new). Cascade deletes children; migration 006 adds `upload_jobs.purged_at` and `user_id` indexes on matches/notifications; `pipeline_runs`, products and job rows are never deleted. Busy jobs (loading/matching) refused with the row locked. App restyled gothic (violet-black, amethyst = yes, crimson, antique gold, verdigris; Cormorant Garamond titles) with more room; landing story section given 620svh of scroll, a static blurred backdrop (the moving 46 px blur caused the flicker) and calmer pops; "built in Surat" lines now say India | Owner's request (re-run demos from a clean slate, start over as a user); admin is a Cognito group granted by hand, never by sign-up; integration test proves the cascade works under `app_ingest` |
| 2026-10-10 | **api Lambda on FastAPI + Mangum** (was a hand-written route table): endpoints are typed functions, auth is a dependency (`Borrower`/`SignedIn`/`Admin`), path/query UUIDs validated by FastAPI (→ 400), one `{"error"}` shape via exception handlers, docs at `/api/docs`. API Gateway, its routes and the JWT authorizer are unchanged. Response models disabled (`PlainRoute`) because pydantic writes `Decimal` as a string. Tests go through the real entry point with full HTTP API v2 events (`tests/unit/apigw.py`). Verified: 31 live requests diffed before/after deploy (status, content type, body, security headers identical); upload → B → C live (4 users, 108 matches, proof ok, 4 emails, link signing logged); instant check → dashboard → preferences → delete in the real UI. Cold start ≈ 0.6 s → ≈ 0.7–1.3 s | Owner's choice: code they can explain in an interview; the slower cold start was accepted knowingly |
| 2026-10-10 | **Robustness after a live "internal error":** one `/me` poll hit a 5 s RDS connect timeout (RDS idle and healthy; the only one in 48 h) and the Check page gave up on that single failure. Fixes: the DB connect is retried once (safe: nothing sent yet); an unreachable DB is a 503 with a clear message, not a 500; the app retries GETs twice on a network error or 5xx (never writes, so nothing is submitted twice). **Uploads as records:** `GET /uploads` + an Uploads table (View / Delete per upload); the uploading browser gets a signed delete key (purpose-separated HMAC, 30 days) so it can delete its own upload without an admin account; admins can delete any. Default charts = upload with the most users; `/ops/runs` always includes the full-file reference run (test traffic had pushed it out of the latest 20) | Owner hit the error live; owner asked to delete and re-upload CSVs as separate records |
| 2026-10-10 | **Numbers review → compile fix:** "Axis Bank 10,000 eligible" is correct (min income ₹15,000; every user earns ≥ ₹25,000), but 7 products whose lender publishes **no** criteria were counted eligible (Federal Bank 10,000/10,000): compile.js filtered out our own "criteria not published" note, leaving no rules and no requirements. Fix: the note is kept as a requirement (test), migration 007 patches cached `criteria_rules` deterministically, and the 10k upload was re-matched via the sweeper (run `80864307`: 580,000 pairs, 164 classes, 0 LLM calls / 44 cached, proof exact). Eligible users per lender matched an independent recomputation from `users.csv` for all 10 charted lenders | Owner asked to re-check the numbers; README quotes only measured runs; evidence exported |
| 2026-10-10 | **Merchant console + uploads behind sign-in:** every `/uploads` route behind the Cognito authorizer; `upload_jobs.account_id` (migration 008); list / progress / delete only for the owner or an admin (others get 404; progress holds rejected raw lines). The browser delete key and the old `/upload` page are retired (`/upload` redirects). `/app/merchant` holds Bulk upload and Single lookup; the landing gets a quiet *Merchant login* in its top bar. App restyled to the owner's monochrome reference (black/white chrome, colour only in data), metrics by default, history/runs/retries behind expand rows, long result lists collapsible | Owner: reviewers share one DB, so uploads must be per account; keep the consumer pitch undisturbed |
| 2026-10-10 | **Production-grade sign-in:** forgot / reset password (Cognito ForgotPassword + ConfirmForgotPassword; the pool already recovers by verified email), show-password, clearer errors; "Continue with Google" via a Cognito managed-login domain + Google IdP (OAuth code flow + PKCE, public client, attribute mapping incl. `email_verified`), behind a deploy flag until the owner's Google OAuth client exists (secret via a Secrets Manager dynamic reference, verified in the CloudFormation docs to work in any property). Accounts resolve one row per verified email so Google and password sign-ins share uploads. Uploads (View / Delete) moved into the Bulk workspace instead of a collapsed section | Owner could not sign in (forgot password; sign-in sends no email by design) and could not find delete |
| 2026-10-10 | **Every account starts fresh:** CSV `user_id`s are global keys, so a second reviewer uploading the sample file saw every row "unchanged" and nothing ran. Owned uploads now get account-scoped customer ids (UUIDv5(account, CSV id)) in ingest: fresh per account, idempotent within one. Console scoped to the signed-in account (analytics empty state; reference only for visitors and admins), *Reset my workspace* (`DELETE /uploads`, own uploads; `?scope=all` admin), loading bar for charts, charts scrolled into focus after View or a finished upload, "Your uploads" collapsible. Also fixed: upload calls never sent the ID token (401) | Owner: reviewers must be able to test end to end from a clean slate |
| 2026-10-11 | **Hardening pass against an external audit (one commit per item, golden master first):** golden-master fingerprint test (ingest counts, reject reasons, every match) generated before any change and unchanged since; pre-write proof in B1 (migration 010); per-send recording in C and C1 composing every skipped user's email (migration 012); crawl-health alert in A; one-line notes on every node; account isolation on `/analytics` and `/ops/runs` with per-account / per-visitor caps (migration 011); `ingestDlq` consumer; Lambdas on `sslmode=verify-full`; streaming ingest behind `INGEST_STREAMING` (turned on after both paths gave identical fingerprints); concurrency tests; coverage gate and mypy in CI; independent recompute script; scale benchmark; measured cost | Each closes a listed deduction without changing outcomes; core-path deploys finished before the 12-hour freeze |
| 2026-10-11 | **Concurrency test found a real deadlock:** two uploads sharing users locked rows in opposite orders (`DeadlockDetected` reproduced with the `ORDER BY` removed). The upsert now locks in `user_id` order on both ingest paths | Found by N7, fixed in the same commit |
| 2026-10-11 | **Live regression, fixed in the same hour:** n8n's plain Postgres query parameters broke on the email body (newlines), so C stopped after its first send. Send and error records now pass one JSON parameter; a workflow test fails if free text reaches a plain parameter; the run was completed by re-running C (one duplicate test email) | Plan vs reality: n8n parameter handling is not safe for free text |
| 2026-10-11 | **Sign-in fixes:** a Google-only account has no password, and Cognito (user-existence protection) silently sends no reset code; the reset screen now says so. Google kept reusing the last account: Cognito domain moved to managed login (v2, in-place) + default branding style, so `prompt=select_account` is forwarded (verified in the docs and live); sign-out revokes the refresh token and ends the Cognito session | Owner report; verified against the Cognito authorize-endpoint docs |
| 2026-10-11 | **Robust under load (owner report: "internal error", a run stuck at emails, B1 still running):** measured, not guessed. n8n's default DB pool (2 connections, 20 s connect, 30 s idle eviction) hit connect timeouts on every 10k run and once lost its DB mid-run; the api opened a new TLS connection per request and timed out at 10 s. Fixes: n8n pool 6 / 60 s / 10 min (documented env vars); B's sweeper re-proves and finishes runs that matched but never recorded emails; C always reaches its finish step; Postgres statement and idle-transaction limits for the app roles; api 28 s timeout, one reused connection per container, analytics stored per upload version (013), uploads list from run counters; console survives reloads, reconnects, retries charts, View goes to Analytics, "While you wait" panel. Same load test before/after: 4 × 503 → 0 errors | Every change verified live with the load that broke it |
| 2026-10-11 | **Memory-starved RDS (owner: upload stuck again):** the ingest Lambda timed out connecting (26 s) because the 1 GB db.t4g.micro was swapping with a 643 MB `matches` table from many 10k test uploads; SQS then waited 12 min to retry. A resize to db.t4g.small was refused (free-plan account; stack rolled back cleanly). Fixes: deletes are chunked and resumable (a 10k delete had also timed out and rolled back); the load-test uploads were deleted (matches 770k → 393k rows); **Stop** cancels an upload before its file loads; the wait panel says when the file is waiting for the database | Plan vs reality: account plan limits the instance size |
| 2026-10-11 | **Upload stuck again after a delete (owner report):** logs showed ingest's connect timing out (3 × 8 s) while RDS was deleting the previous 10k upload; a re-upload made during that delete counted the doomed rows as "unchanged" and lost them (0 customers), the workspace reset hit the 2-minute emailing guard, and the public analytics went empty once the operator's upload was deleted. Fixes: ingest waits ~1 min for the database; **one live upload per account** (409 with what blocks it; the console offers to clear it, then uploads the new file); **Stop is a clean exit** (cancel, or let matching finish then delete; a run stuck 15+ min can be ended); deletes wait out the emailing window instead of failing; the public reference falls back to the charts kept at delete time; a workspace reset keeps each upload's charts | Logs, RDS metrics and DB rows from the failed attempt |
| 2026-10-11 | **Capacity guard + kept figures (owner request):** new uploads wait (503 with a "ask the others to delete, or try in ~10 min" message) while bulk uploads hold 30,000+ customers; example emails are kept with the analytics snapshot at delete time (owner-only route; stripped from public analytics); "Your last run" metrics read the run counters, so they survive a delete. Auto-deleting old uploads was considered and skipped (more moving parts in n8n near the deadline; the delete prompts and the admin reset cover it) | Owner question about 4 concurrent reviewers |
| 2026-10-11 | **One upload in the whole database (owner decision) + delete timeout:** the 30,000-customer cap became one stored upload across all accounts. "Delete every account's uploads" hit the API's 28 s limit (charts for two 10k uploads, then a 15 s delete budget): one 18 s budget per call now covers both, chunks are 1,000, and the console retries a cut-off call. Also found live: example emails' UUIDs broke the snapshot JSON (fixed, real-DB test) | Logs: `Status: timeout` at 28 s; `TypeError: UUID` |
