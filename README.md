# Loan Eligibility Engine

An event-driven system on **AWS + self-hosted n8n** that ingests a users CSV, discovers
personal-loan products by crawling lender and comparison sites, matches every user to the
products they are likely eligible for, and emails each matched user their best options.

| | |
|---|---|
| **Live upload UI** (merchant console: sign up with any email, then upload) | https://t7lcgp5o0j.execute-api.ap-southeast-2.amazonaws.com/app/merchant |
| **Landing + app** (extra) | https://t7lcgp5o0j.execute-api.ap-southeast-2.amazonaws.com/ (app at `/app/`, [§14](#14-extra-landing-page-app-and-accounts-one-product)) |
| **Region** | `ap-southeast-2` (Sydney): the only region this AWS account's organization allows (see [Trade-offs](#11-trade-offs--production-next-steps)) |
| **n8n** | self-hosted 2.42.5 on EC2, **not exposed to the internet**: reached through an SSM tunnel |
| **LLM** | Amazon Bedrock · Nova Pro (temperature 0), via n8n with **no AWS access keys** |
| **Email** | Amazon SES via n8n's **AWS SES node**, to the owner's test `+aliases` only |
| **Proof** | [`docs/evidence/REQUIRED_PATH.md`](docs/evidence/REQUIRED_PATH.md): each required path checked on the live stack (n8n execution log, RDS rows, emails, CI) · [screenshots](docs/screenshots/) |

**Headline result (measured, not estimated):** matching 10,000 users against 59 crawled
products would be **590,000** user×product evaluations for a naive LLM approach. The
pipeline reduced that to **164 equivalence classes** and **5 LLM calls in total (≈ $0.024)**,
then **0 calls** on every later run, and a brute-force check proves the optimized result is
**identical** to evaluating all 590,000 pairs one by one.

### Reviewer quick start
1. **Upload:** open the [merchant console](https://t7lcgp5o0j.execute-api.ap-southeast-2.amazonaws.com/app/merchant), sign up with any email (Cognito sends a 6-digit code; check Spam), then **Upload CSV** with [`tests/fixtures/demo_users.csv`](tests/fixtures/demo_users.csv). Your workspace starts empty.
2. **Watch it run** (about 30 s): Uploaded → Validated and loaded (the row with credit score 950 is rejected, with its reason) → Matched (Workflow B) → Notified (Workflow C).
3. **Emails** go only to the owner's three Gmail test `+aliases`, never to CSV addresses. The console shows the emails that were sent ("Emails sent for this upload"), and the received email is in the [screenshot](docs/screenshots/14-email.png) and the video.
4. **Treasure Hunt:** [§8](#8-the-optimization-treasure-hunt) and the raw measurements in [`docs/evidence/`](docs/evidence/). **Every required path checked live:** [`REQUIRED_PATH.md`](docs/evidence/REQUIRED_PATH.md).
5. **n8n:** credential setup in [§5](#5-configuring-credentials-inside-n8n); workflows node by node in [§6](#6-workflows-a--b--c-node-by-node); to run n8n locally without AWS, see [§4.7](#47-run-n8n-locally-without-aws-for-reviewers).

### Review in 10 minutes
1. [§8 The Treasure Hunt](#8-the-optimization-treasure-hunt): the funnel figure, the measured numbers and the scale table.
2. [`sql/matching/stage1_classes.sql`](sql/matching/stage1_classes.sql): equivalence classes from cut points, in one statement.
3. [`n8n/workflows/B1_match_run.json`](n8n/workflows/B1_match_run.json): the matching workflow (importable locally, [§4.7](#47-run-n8n-locally-without-aws-for-reviewers)); every node has a one-line note on the canvas.
4. [`loan_engine/ingest/handler.py`](loan_engine/ingest/handler.py) and [`repository.py`](loan_engine/ingest/repository.py): one transaction per file, streaming COPY, idempotent upsert.
5. [`serverless.yml`](serverless.yml): the network (no NAT, VPC endpoints) and one IAM role per function.
6. [`docs/evidence/REQUIRED_PATH.md`](docs/evidence/REQUIRED_PATH.md): every required path, measured on the live stack.
7. [`tests/integration/test_golden.py`](tests/integration/test_golden.py): the golden master that pins ingest and matching outcomes.
8. The demonstration video (link in the submission form).

---

## Contents
1. [What happens end to end](#1-what-happens-end-to-end)
2. [Architecture](#2-architecture)
3. [Design decisions](#3-design-decisions)
4. [Deploy step by step](#4-deploy-step-by-step)
5. [Configuring credentials inside n8n](#5-configuring-credentials-inside-n8n)
6. [Workflows A / B / C node by node](#6-workflows-a--b--c-node-by-node)
7. [Web crawling strategy](#7-web-crawling-strategy)
8. [The Optimization Treasure Hunt](#8-the-optimization-treasure-hunt)
9. [Failure handling](#9-failure-handling)
10. [Security](#10-security)
11. [Trade-offs & production next steps](#11-trade-offs--production-next-steps)
12. [Code quality & tests](#12-code-quality--tests)
13. [Repository layout](#13-repository-layout)
14. [Extra: landing page, app and accounts](#14-extra-landing-page-app-and-accounts-one-product)

---

## 1. What happens end to end

1. **Upload**: the merchant signs in to the upload page and picks a CSV. The page asks the API for an
   upload ticket (a **presigned POST**), then sends the file **straight to S3**: the API never
   handles the file, so API Gateway's request size and time limits do not apply.
2. **Ingest**: S3 drops an event on an **SQS queue**; the **ingest Lambda** (inside the VPC)
   streams the CSV from S3 line by line, validates every row and pipes it straight into
   **RDS PostgreSQL** with one `COPY`, in one transaction; duplicates are resolved and valid rows
   upserted in SQL. Memory stays flat whatever the file size (0.1 MB of Python memory on a
   50 MB file, measured). Bad rows are stored with their line number and reason and shown in the UI.
3. **Match (Workflow B)**: after the commit, the Lambda calls an **n8n webhook** over the private
   network. B claims the job and runs the multi-stage matching pipeline (B1). A brute-force proof
   checks every user × product pair **before** any match is written and again **after**.
4. **Notify (Workflow C)**: B hands over to C, which builds each user's personalized email
   (**best pick + top picks**, with the reason for each) and sends it through the **AWS SES
   node**. The SES sandbox caps real sends at 5 per run. Every other user's email is still built
   and stored (sub-workflow C1), so only delivery is capped.
5. **Discover (Workflow A)**: independently, **every day at 06:00 IST**, A crawls lender and
   comparison sites, extracts eligibility criteria with Nova Pro, and keeps `loan_products` fresh.

The upload page tracks every stage live (Uploaded → Ingested → Matched → Notified).

---

## 2. Architecture

The short version (seven boxes):

```mermaid
flowchart LR
  browser([Browser]) -->|"upload ticket, then the file"| edge["API Gateway + λ api<br/>S3 (presigned POST)"]
  edge -->|ObjectCreated| sqs[["SQS"]]
  sqs --> ingest["λ ingest<br/>stream · validate · COPY"]
  ingest --> rds[("RDS PostgreSQL")]
  ingest -->|webhook| n8n["n8n on EC2<br/>A crawl · B match · C notify"]
  n8n <--> rds
  n8n -->|"Nova Pro · SES"| aws["Bedrock · SES"] --> inbox([Gmail test inbox])
```

The detailed version:

```mermaid
flowchart LR
  user([User / browser])
  web(["Lender & comparison sites<br/>robots.txt respected"])
  gmail(["Test inbox<br/>+aliases"])
  dev(["Developer laptop"])

  subgraph AWS["AWS · ap-southeast-2"]
    apigw["API Gateway<br/>HTTP API, throttled"]
    s3[("S3 data bucket<br/>raw/ · fixtures/ · config/")]
    sqs[["SQS ingest queue"]]
    dlq[["DLQ after 3 tries"]]
    dlqfn["λ ingestDlq<br/>marks the job FAILED"]
    sm[("Secrets Manager")]
    bedrock["Bedrock · Nova Pro"]
    ses["SES"]
    cognito["Cognito user pool<br/>accounts · email codes"]
    cw["CloudWatch alarms<br/>DLQ · Lambda errors → SNS email"]
    subgraph VPC["VPC · no NAT Gateway"]
      subgraph PUB["public subnet · outbound only"]
        n8n["EC2 · n8n 2.42.5 in Docker<br/>A · A1 · B · B1 · C · C1 · E (errors)"]
      end
      subgraph PRIV["private subnets"]
        api["λ api<br/>landing + app · upload tickets · status<br/>dashboard · accounts (JWT)"]
        ingest["λ ingest<br/>validate · COPY · upsert"]
        migrate["λ migrate<br/>schema · roles · grants"]
        rds[("RDS PostgreSQL 17<br/>private · TLS · encrypted")]
        vpce["VPC endpoints<br/>S3 gateway · Secrets Manager"]
      end
    end
  end

  user -->|"/ · /app · POST /uploads · /check"| apigw --> api
  user -->|"sign up / sign in"| cognito
  cognito -.->|"JWT authorizer on /account"| apigw
  user -->|"presigned POST: the file"| s3
  api --> rds
  s3 -->|ObjectCreated| sqs --> ingest
  sqs -.->|3 failures| dlq --> dlqfn
  dlqfn --> rds
  dlqfn -.-> cw
  ingest --> rds
  ingest -->|"webhook: private IP + header secret"| n8n
  api -.-> vpce
  ingest -.-> vpce
  migrate -.-> vpce
  migrate --> rds
  vpce -.-> sm
  vpce -.-> s3
  n8n --> rds
  n8n -->|crawl over HTTP| web
  n8n -->|"AssumeRole → Converse"| bedrock
  n8n -->|AWS SES node| ses --> gmail
  n8n -->|"signed dashboard links: POST /internal/email-tokens"| apigw
  dev -->|"SSM port forwarding: no SSH, no open ports"| n8n
```

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser
  participant API as λ api
  participant S3 as S3
  participant Q as SQS
  participant I as λ ingest
  participant DB as RDS
  participant N as n8n (B → B1 → C)
  participant SES as SES
  B->>API: POST /uploads {filename}
  API->>DB: INSERT upload_jobs (AWAITING_UPLOAD)
  API-->>B: job_id + presigned POST (key pinned, text/csv, ≤ 50 MB, 10 min)
  B->>S3: multipart POST (file goes straight to S3)
  S3->>Q: ObjectCreated event
  Q->>I: message (batch 1, max 2 concurrent)
  I->>DB: one transaction: claim job → stream rows through COPY → rejects + upsert (user_id order) → COMPLETED
  I->>N: POST /webhook/ingest-complete (X-Webhook-Secret), after COMMIT only
  N->>DB: claim job (atomic) → Stage 0..2 → pre-write proof → Stage 3 (matches) → post-write proof
  N->>SES: up to 5 emails per run (sandbox), 1/s, each recorded at once
  N->>DB: every other user's email composed and stored (C1, 500 per batch)
  B->>API: GET /uploads/{job_id} (every 2 s): ingested → matched → notified
```

**Why n8n sits in a public subnet but is private:** it needs *outbound* internet (lender sites,
Bedrock, SES) and there is no NAT Gateway, so it has a public IP for egress only. Its security
group allows **one** inbound rule: TCP 5678 from the ingest Lambda's security group (the
webhook). No SSH, no port 80/443, no editor exposure; the editor is opened through SSM.

---

## 3. Design decisions

| Decision | Why |
|---|---|
| **Claim-check upload**: presigned POST → S3 → SQS → Lambda | The assignment warns that a Lambda-backed API endpoint hits size/time limits. The browser uploads directly to S3; S3 enforces the key (`raw/<job_id>.csv`), content type and 1 B–50 MB size itself. |
| **SQS between S3 and the Lambda** (not a direct S3 trigger) | Retries with a 720 s visibility timeout (6× the function timeout), a dead-letter queue after 3 failures, and `maximumConcurrency: 2` to protect RDS connections. |
| **One transaction per file** | A job is either fully loaded or not at all. `SELECT … FOR UPDATE SKIP LOCKED` makes duplicate deliveries harmless; the webhook fires only after COMMIT. |
| **Idempotent upsert** | Users are upserted only when values actually change (`IS DISTINCT FROM`); unchanged users keep their old job id, so re-uploading the same file creates **0** new matches and **0** emails (verified live). |
| **No NAT Gateway; VPC endpoints instead** | Private Lambdas only need S3 and Secrets Manager. Endpoints are cheaper and do not open a path to the whole internet. |
| **Least-privilege everywhere** | One IAM role per Lambda scoped to exact ARNs; three Postgres roles (§10); n8n's AWS access is a role that can only send email and call Nova Pro. |
| **n8n stores its own data in RDS** | Workflows, credentials and executions survive an instance rebuild. The credential-encryption key lives in Secrets Manager with `DeletionPolicy: Retain`. |
| **Pinned versions** | n8n 2.42.5, Postgres 17.11, AMI id, Docker Compose 5.5.1 (SHA-256 checked), Playwright 1.63.0: a redeploy can never silently change behavior. |
| **Pluggable seams** | Validation rules (`VALIDATION_RULES` env JSON), the next-stage notifier (`Notifier` protocol), crawl sources (`crawl_sources` table), and prompts (versioned files) change by config, not by rewriting infrastructure. |
| **Text JSON, not a forced tool call** (measured) | Tried Bedrock's schema-forced tool use (`toolChoice.tool`) for both Nova calls. Values were identical on a single page, but on a real 5-page batch Nova called the tool **once** and returned only **1–2 of 5 pages** (live crawl: 19 of 25 pages failed safe). Text mode returns 5/5 (40/40 on the full crawl), so batching wins: the answer stays a JSON array, parsed defensively, and every quote is verified against the page. |
| **FastAPI behind API Gateway, one Lambda** (Mangum adapter) | API Gateway keeps the edge: routes, throttling and the Cognito JWT authorizer. Inside the api Lambda, FastAPI declares each endpoint as a typed function: path ids are parsed as UUIDs (bad ones → 400), and auth is a dependency (`Borrower`, `SignedIn`, `Admin`). Every error has one shape, `{"error": …}`. Interactive docs are served at `/api/docs`. Cost: cold start went from ≈ 0.6 s to ≈ 0.7–1.3 s (measured), only on the first request of a fresh container. Response models are switched off so database decimals stay JSON numbers; a test pins this. Migrated with 31 live requests diffed before and after (identical) plus the full upload → B → C path re-run live. |
| **Streaming ingest** (constant memory) | Rows go from the S3 stream through `COPY` into a transaction-local staging table; duplicates (last one wins), rejects and the upsert are one SQL statement. On a 50 MB, 520,000-row file: 0.1 MB peak Python memory vs 312.7 MB for the first in-memory version ([measured](docs/evidence/ingest_bench_2026-10-11.json)). The upsert locks rows in `user_id` order, which fixed a real deadlock between two uploads sharing users (found by a concurrency test). |
| **Two correctness proofs** | Before Stage 3 writes anything, the class decisions expanded to users must equal a naive per-user evaluation; after it, the stored matches must too. A wrong decision stops the run with **zero** matches written. |
| **Every send recorded at once** | Workflow C writes each email's row the moment SES answers, so a crash mid-loop never emails anyone twice; the demo cap counts sends already recorded. |
| **Accounts own their data** | Uploads, their analytics and their emails are visible only to the uploading account (or an admin); signed-out visitors see only the operator's reference dataset. Daily caps per account and per visitor (a keyed hash of the IP, never the IP). |
| **Workflow JSON is generated** | `n8n/build_workflows.py` assembles every Code node from `n8n/code/*.js` (unit-tested with `node --test`) and every prompt from `n8n/prompts/*.md`, so the running workflow can never drift from the tested code. |

The full reasoning trail, including what changed when reality disagreed with the plan, is in
the decision log at the end of [PLAN.md](PLAN.md).

---

## 4. Deploy step by step

### 4.1 Prerequisites
- AWS CLI v2 (logged in), the **Session Manager plugin**, Node.js 18+, **Serverless Framework v4**
  (`npm i -g serverless`, then `serverless login`), Python 3.12 (e.g. `uv python install 3.12`), Docker.
- **SES**: verify the sender and each test alias (sandbox mode sends to verified addresses only):
  ```bash
  for e in you@gmail.com you+one@gmail.com you+two@gmail.com you+three@gmail.com; do
    aws sesv2 create-email-identity --region ap-southeast-2 --email-identity "$e"; done
  ```
  Click the four verification links. Then set `SES_FROM` / `TEST_ALIASES` in `n8n/build_workflows.py`.
  (Identities are created by hand on purpose: each one needs its owner to click the emailed link,
  which CloudFormation cannot do; the stack only grants n8n permission to send from them.)
- **Bedrock**: Amazon Nova Pro is available by default in `ap-southeast-2` (no model-access form).

### 4.2 Python environment (also used to package the Lambdas)
```bash
uv venv --python 3.12 && uv pip install -r requirements-dev.txt pip
```

### 4.3 Deploy the AWS stack (everything is in `serverless.yml`)
Run these in order (each step needs the previous one):
```bash
scripts/build-frontends.sh       # 1. landing (web/) + app (dashboard/) into the api package
serverless deploy                # 2. VPC, endpoints, RDS, S3, SQS/DLQ, alarms, Lambdas, API, Cognito, EC2, IAM, secrets (~15 min first time)
scripts/n8n-sync.sh push         # 3. n8n's boot script + compose file to the bucket created in step 2
aws lambda invoke --function-name loan-engine-dev-migrate --payload '{}' /tmp/out.json && cat /tmp/out.json   # 4.
```
- Step 3 can only run after step 2 (it reads the bucket name from the stack). The EC2 instance
  created in step 2 simply waits, retrying every 15 s, until the boot script appears.
- Step 4 (`migrate`) applies `sql/001…012` once each, creates the three database roles with
  passwords generated in Secrets Manager, re-applies `sql/R__grants.sql`, and creates n8n's
  database and its `n8n_meta` role. n8n becomes healthy only after this step.
- Confirm the SNS email ("AWS Notification - Subscription Confirmation") sent to the alarm alias,
  so CloudWatch alarms (DLQ not empty, Lambda errors) reach you.

The EC2 instance boots n8n by itself (`deploy/n8n/boot.sh`, about 2–3 minutes): it installs Docker,
reads its secrets through the instance role, writes `.env` (mode 600), and starts the container.

### 4.4 Open n8n, create the owner account and the 3 credentials
```bash
scripts/tunnel-n8n.sh            # keep running, open http://localhost:5678
```
Then follow [§5](#5-configuring-credentials-inside-n8n).

### 4.5 Import the workflows
The exports reference credentials by id. On a fresh n8n, put the ids of the three credentials you
created in §5 (open each credential: the id is in the URL) into the environment, then regenerate:
```bash
export N8N_CRED_PG=<postgres id> N8N_CRED_AWS=<aws id> N8N_CRED_WEBHOOK=<header auth id>
.venv/bin/python n8n/build_workflows.py   # regenerate n8n/workflows/*.json from tested sources
scripts/n8n-workflows.sh import           # import + publish via the n8n CLI over SSM
scripts/n8n-workflows.sh run LoanEngineWfA001   # first crawl now (otherwise daily 06:00 IST)
```

### 4.6 Try it
Open `<UploadUiUrl>app/merchant` (output `UploadUiUrl` from `serverless info`), create an account
(email + password, confirmed with an emailed code), and upload a CSV. Uploads belong to the
signed-in account, so several reviewers can share one database without seeing each other's files.
From a terminal (the password is typed into `id-token.sh`, never echoed):
```bash
export ID_TOKEN="$(scripts/id-token.sh you@example.com)"
scripts/upload-sample.sh "$(scripts/stack-output.sh UploadUiUrl)" tests/fixtures/demo_users.csv
```
![Upload UI after a run](docs/screenshots/01-upload-ui.png)

### 4.7 Run n8n locally without AWS (for reviewers)
```bash
cp .env.example .env && docker compose --profile local up -d   # n8n + a local Postgres
```

---

## 5. Configuring credentials inside n8n

n8n needs three credentials. **None of them is an AWS access key**, and no secret is
stored in this repo or in the exported workflow JSONs. Every secret is generated by
AWS Secrets Manager at deploy time and copied once into n8n, which encrypts it with
`N8N_ENCRYPTION_KEY` (itself a Secrets Manager secret, retained even if the stack is
deleted).

### 5.0 Open the n8n editor (private, via SSM)

n8n has **no inbound internet access** (no public port, no SSH). Open it through an SSM
port-forwarding tunnel:

```bash
scripts/tunnel-n8n.sh          # keep running; then open http://localhost:5678
```

Prerequisites: AWS CLI v2 + the Session Manager plugin. On first visit n8n asks you to
create the owner account.

![n8n workflows](docs/screenshots/02-n8n-workflows.png)

### 5.1 Postgres: the engine database (`app`) as the least-privilege role

Copy the generated password straight to the clipboard (it is never printed):

```bash
aws secretsmanager get-secret-value --region ap-southeast-2 \
  --secret-id loan-engine/dev/db/n8n_workflows --query SecretString --output text \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['password'], end='')" | pbcopy
```

**Credentials → Create credential → Postgres**

| Field | Value |
|---|---|
| Host | the stack output `DbEndpoint` (`scripts/stack-output.sh DbEndpoint`) |
| Database | `app` |
| User | `n8n_workflows` |
| Password | paste |
| SSL | **Require** |
| Ignore SSL Issues | **off**: the certificate is really verified (see below) |
| Port | `5432` |

Why "Require" works *with* verification: the n8n container trusts the AWS RDS CA bundle
via `NODE_EXTRA_CA_CERTS` (set by `deploy/n8n/boot.sh`).

`n8n_workflows` can only read users, update the match-progress columns of
`upload_jobs`, and read/write the matching tables. It cannot delete anything or change
the schema (see [Security](#10-security)).

![Postgres credential](docs/screenshots/03-cred-postgres.png)

### 5.2 AWS: for the SES (email) and Bedrock (Nova Pro) nodes, with no keys

**Credentials → Create credential → AWS (Assume Role)**

| Field | Value |
|---|---|
| Use System Credentials | **on**: starts from the EC2 instance role |
| Region | `ap-southeast-2` |
| Role ARN | stack output `N8nAwsRoleArn` |
| External ID | stack output `N8nAwsRoleExternalId` (`loan-engine-dev-n8n`) |
| Role Session Name | `n8n` |

How it works: n8n (with `N8N_AWS_SYSTEM_CREDENTIALS_ACCESS_ENABLED=true`) uses the EC2
instance profile, then assumes `loan-engine-dev-n8n-aws`. That role can only
`ses:SendEmail`/`SendRawEmail` and `bedrock:InvokeModel` on `amazon.nova-pro-v1:0`.
Its trust policy accepts only the n8n instance role **and** the External ID. The
instance metadata hop limit is 2 so the container can reach the instance role.

![AWS Assume Role credential](docs/screenshots/04-cred-aws-assume-role.png)

### 5.3 Header Auth: the ingest → n8n webhook secret

```bash
aws secretsmanager get-secret-value --region ap-southeast-2 \
  --secret-id loan-engine/dev/n8n/webhook-token --query SecretString --output text \
  | tr -d '\n' | pbcopy
```

**Credentials → Create credential → Header Auth**: Name `X-Webhook-Secret`, Value: paste.
The ingest Lambda sends the same header; the webhook is also reachable only from the
Lambda security group on the private network.

![Header Auth credential](docs/screenshots/05-cred-header-auth.png)

![Credentials list](docs/screenshots/06-credentials-list.png)

---

## 6. Workflows A / B / C node by node

All eight workflows (A, A1, B, B1, C, C1, E and the E1 drill) are in [`n8n/workflows/`](n8n/workflows/). Each opens with a sticky note
that explains it, and **every node shows a one-line note under it on the canvas** (what it does
and why; a test checks that none is missing).

### A · Loan product discovery (crawler), daily 06:00 IST + manual run
![Workflow A](docs/screenshots/07-workflow-A.png)

| Node | What it does |
|---|---|
| **Every day 06:00 IST** / **Run now (demo)** | Schedule trigger (the assignment's trigger) and a manual trigger for demos. |
| **Start run** (Postgres) | New `run_id` + the enabled rows of `crawl_sources`: sites are configuration, not code. |
| **Origins to check → Fetch robots.txt → Robots rules** | Fetches each site's robots.txt once; an RFC 9309 parser (`robots.js`) decides every URL. |
| **Hub sources → Fetch hub pages → Discover pages** | Follows lender links on comparison-site hubs, drops non-lender pages, adds the direct bank pages, and orders pages **round-robin across sites** so no site is hit twice in a row. |
| **robots.txt allows?** | Disallowed pages are logged as `robots_disallowed` and **never fetched**. |
| **Every 5 pages → Process batch (A1)** | Loop: each batch of 5 goes to the sub-workflow, so results are written batch by batch (streaming). |
| **Run summary → Finish run** | Deactivates products that disappeared from pages crawled OK (failed pages keep their data), supersedes their matches, reports per-status counts and tokens. |
| **Products changed? → Re-match changed products (B)** | New or changed products are re-matched against every user (B in product mode). |
| **Crawl health → Crawl degraded? → Email crawl alert (SES)** | A site redesign does not fail the crawl: its pages come back `failed` and old products are kept. [`crawl_health.sql`](sql/matching/crawl_health.sql) compares usable pages per channel with the previous crawl; a drop of more than 30% (or no usable page) is stored in `workflow_errors` and emails the operator at most once a day. |

### A1 · Process page batch (sub-workflow)
![Workflow A1](docs/screenshots/08-workflow-A1.png)

| Node | What it does |
|---|---|
| **Fetch page (1 req/s)** | Plain HTTP GET (browser UA, timeout, retries). Pages flagged `rendered` would go to the optional headless renderer instead (off by default). |
| **Classify fetch** | `ok` / `blocked` (403/429/challenge page: **skipped, never bypassed**) / `failed`. |
| **Live fetch failed? → S3 fixture → Use fixture** | Falls back to a saved snapshot of the page in S3 (`crawl_runs.status = fixture`). |
| **Isolate sections** (`sections.js`) | HTML + embedded JSON-LD → the eligibility and interest-rate sections, found by **scoring** candidate windows (menus that say "eligibility" lose). No section = `failed` (likely layout change): old products are kept. |
| **Hash sections** (Crypto) | SHA-256 of the sections + the prompt/normalizer versions. |
| **Known hashes → Mark changed → Changed?** | Unchanged pages skip the LLM entirely. |
| **Build Nova request → Nova Pro (Converse)** | **One** batched call for all changed pages in the batch (prompt [`extract_criteria_v2`](n8n/prompts/extract_criteria_v2.md)). |
| **Verify + normalize** (`llm.js`, `normalize.js`) | Every criterion must quote evidence that exists on the page and contains its numbers, else it becomes *conditional*; deterministic parsing ("₹3 lakh p.a." → 25,000/month). One product per lender × channel × employment type. |
| **Upsert products + log pages** | One SQL statement per batch (`jsonb_to_recordset`) + a `crawl_runs` row per page. |
| **Unchanged → bookkeeping → Touch last_seen + log pages** | No LLM: just bookkeeping. |

### B · User–loan matching (triggers + claim)
![Workflow B](docs/screenshots/09-workflow-B.png)

| Node | What it does |
|---|---|
| **Ingest complete (webhook)** | `POST /webhook/ingest-complete`, Header Auth, responds immediately. Called by the ingest Lambda after COMMIT. |
| **Sweeper every 10 min → Jobs waiting for matching** | Recovery path ([`sweeper.sql`](sql/matching/sweeper.sql)): completed jobs whose webhook was missed, whose run died (lock older than 15 min), or whose run **failed** (retried up to 3 times, 10 min apart; then it stays FAILED for a human, after Workflow E has alerted). |
| **From A (product mode)** | Re-matches all users against new or changed products. |
| **Claim job + start run** | Atomic `UPDATE … WHERE match_status IS NULL OR stale OR (FAILED and < 3 failures)` + new `pipeline_runs` row ([`claim.sql`](sql/matching/claim.sql)): a duplicate webhook racing the sweeper can never double-match. |
| **Match (B1) → Matching failed? → Mark job failed / Notify users (C)** | Runs the Treasure Hunt; failures mark the job `FAILED` (visible in the UI) instead of hanging. |
| **Products compiled late → Re-match them? → Re-match all users (B, product mode)** | If the LLM failed to compile a product's criteria earlier, that product counted as "may qualify" for everyone; once a later run compiles it, B re-matches every user against exactly those products ([`products_compiled_late.sql`](sql/matching/products_compiled_late.sql)). The follow-up run finds every text cached, so it never loops. |

Hardening: the webhook body is validated (a non-UUID `job_id` is dropped before it reaches SQL);
re-claiming a stale job closes its abandoned run; the sweeper also closes any run still
`running` after 30 min (n8n's hard timeout is 10 min), so `pipeline_runs` never shows ghost runs.
Workflow A calls B in **product mode** with the ids of new or changed products after each crawl.

### B1 · Match one run (the Treasure Hunt), explained in [§8](#8-the-optimization-treasure-hunt)
![Workflow B1](docs/screenshots/10-workflow-B1.png)

**Criteria to compile → Batches of 10 → Nova Pro · compile → Validate compiled rules → Save** (Stage 0, cache misses only) →
**Stage 1+2 · classes & decisions** → **Refresh planner stats** → **Pre-write proof** → **Pre-write passed?**
(the class decisions, expanded to users, must equal a naive evaluation of every pair; otherwise the
run stops with **zero** matches written) → **Stage 3 · expand, score, diff** → **Correctness proof** →
**Proof passed?** (the stored matches are re-checked against every pair; if any differs, the run
stops before notification: B marks the job failed, C is never called, Workflow E alerts) →
**Finish run** → **Treasure Hunt funnel** (one output item: pairs → classes → decisions → AI calls
→ matches → both proofs). The SQL is in [`sql/matching/`](sql/matching/).

### C · Notify matched users (SES)
![Workflow C](docs/screenshots/11-workflow-C.png)

| Node | What it does |
|---|---|
| **Users to email** | New, un-notified matches of the run; the best offer **per lender** (best platform), ranked by tier → fit score → rate, top 5 per user. |
| **Sign dashboard links** | ONE HTTP call per run to the api Lambda's `POST /internal/email-tokens` (same Header Auth credential as the webhook): a signed 14-day link per user. The HMAC key never enters n8n; if signing fails, the emails go out without the link. |
| **Compose emails** (`email.js`) | Personalized HTML + text: best pick, top picks, *why* ("your income is 3.6× the minimum"), *you'll also need…*, disclaimer. All crawled text is HTML-escaped, and only `http(s)` links are rendered. The recipient is a test alias chosen deterministically, and a guard **aborts** on anything else. |
| **One email at a time → Send via AWS SES → Delivery result → Record this send → wait 1.1 s** | The AWS SES node with the Assume Role credential, paced for the SES sandbox (1 email/s). Each send is stored **the moment SES answers** (with its subject and text), so a crash mid-loop never emails anyone twice; the demo cap counts sends already recorded ([`notify_record_send.sql`](sql/matching/notify_record_send.sql)). |
| **All results → one item → Record notifications** | Every other user with new matches is recorded as `skipped_demo` (demo cap of 5 real emails per run); the run's counters are set from the table, so a re-run is idempotent. |
| **Compose the rest (C1) → More to compose?** | Every one of those users' personalized emails is **built and stored** by sub-workflow C1, 500 users per execution (bounded memory on a 10k run), with the same `email.js`. The loop stops when nothing remains, when a batch stores nothing, or after 200 batches. |

**C1 · Compose a batch (sub-workflow):** **Next users to compose** (up to 500 users whose send was
skipped and whose email is not built yet) → **Compose (no send)** (`composeBatch` in `email.js`;
one user's bad data never stops the batch) → **Save composed emails** (subject + text on the
notification row; returns how many remain). C1 has no SES node: it can never send.

![Workflow C1](docs/screenshots/11b-workflow-C1.png)

A received email (best pick, top picks with the reason, the dashboard button):

![Notification email](docs/screenshots/14-email.png)

### E · Error handler (the error workflow of A, A1, B, B1 and C)
![Workflow E](docs/screenshots/13-workflow-E.png)

| Node | What it does |
|---|---|
| **On workflow error** (Error Trigger) | n8n starts E whenever a production execution of another workflow fails (schedule, webhook, sub-workflow). |
| **Summarize error** (`errors.js`) | Flattens both n8n payload shapes (execution failure / trigger failure) into one record; never throws, bounds the message, escapes it for HTML. |
| **Record error** | Inserts into `workflow_errors` and decides whether to alert: **at most one email per workflow per 30 min**, so a failing schedule cannot drain the SES sandbox quota. |
| **Alert due? → Email alert (SES)** | Alert to the test alias; a failed alert never fails the handler (the row is already stored). E has no error workflow itself (no loop). |
| **Drill: simulate an error** | Manual trigger that replays a sample payload through the same nodes. |

**E1 · Error drill** fails on purpose. `scripts/n8n-workflows.sh drill` publishes it for one
scheduled run and unpublishes it again. Verified live: E1 execution 89 → `workflow_errors` row
with workflow, node and message → alert email.

---

## 7. Web crawling strategy

**Sources (measured from the EC2's Sydney IP, identical to an Indian home IP):** 45 candidate
pages discovered → **40 usable** ([`docs/crawl_inventory.json`](docs/crawl_inventory.json)):

| Channel | Discovery | Usable pages |
|---|---|---|
| **BankBazaar** | hub page → per-lender links | 25 |
| **Paisabazaar** | hub page → per-lender links | 10 |
| **Direct lender sites** | each bank's own `sitemap.xml` (Indian banks moved to `*.bank.in`) | 5 (ICICI, IDFC FIRST, Tata Capital, IndusInd, SBI) |

Excluded, with the reason kept in `crawl_sources`: HDFC and Kotak's own sites (**robots.txt
disallows**, respected; their offers still come via the aggregators), Bank of Baroda
(**403 firewall** for bots: never bypassed), Axis's direct page (criteria load client-side),
Policybazaar (no personal-loan products; that group's loans are on Paisabazaar).

**Why multiple channels:** the same lender publishes different numbers on different platforms.
Live example: *Kotak via BankBazaar* ₹20,000/month, 10.99–16.99%; *Kotak via Paisabazaar*
₹25,000/month, CIBIL 760, from 9.95%. Products are therefore **lender × channel × employment
type** (59 active products, 26 lenders), and the email shows the best platform per lender.

**Robustness rules**
- **Polite:** robots.txt obeyed per URL; 1 request/s; pages interleaved across sites; a browser-compatible User-Agent that names the project.
- **No evasion:** a 403/429/CAPTCHA means *skip*. The optional headless renderer (`renderer/`,
  Playwright, off by default) is only for sites that allow plain HTTP but load data client-side,
  and it is SSRF-guarded (it refuses private and metadata IPs).
- **HTML + embedded data:** JSON-LD blocks (FAQ pages) are read, because JS-heavy sites ship content there.
- **Layout changes:** sections are found by scoring windows, not by brittle CSS selectors; if
  nothing scores, the page is marked `failed` and its existing products are kept.
- **Change detection:** unchanged sections = zero LLM calls. Measured: first crawl 41 pages in
  1 min 27 s (42.5k input tokens); a repeat crawl **35 s and 0 tokens**.
- **The LLM extracts, the code does the math, and evidence is verified:** v1 of the prompt swapped
  IIFL's salaried and self-employed age bands; v2 makes every criterion quote its source, and the code
  rejects quotes that are not on the page or lack the numbers. 33 of 59 products are fully verified;
  the rest are kept as *conditional* (never used to reject anyone).

---

## 8. The Optimization Treasure Hunt

**The problem:** asking an LLM about every user × product pair is slow and expensive
(10,000 × 59 = 590,000 calls). **The solution:** move the LLM *off* the per-user path entirely,
and make the remaining work exact and set-based.

| Stage | Where | Idea | Scales with |
|---|---|---|---|
| **A · extraction** | Workflow A | The LLM reads each lender page once (and again only when it changes). | changed pages |
| **0 · compile criteria** | B1 · Nova Pro | Each product's free-text conditions → **checkable rules** (`credit_score ≥ 750`, `age ≤ 60`, per employment type) and **requirements** we can't check ("2 years' experience", "metro cities"). Cached by text hash + prompt version. | **distinct criteria texts** |
| **1 · equivalence classes** | B1 · SQL | Every threshold any product or rule uses is a **cut point**. Users whose income, score and age fall between the same cut points, with the same employment type, get identical answers to every rule → one class. **Exact, not banded.** | users → classes |
| **2 · decisions** | B1 · SQL | Hard criteria + compiled rules evaluated once per class × product → eligible / conditional / not eligible. | class × product |
| **3 · expand, score, diff** | B1 · SQL (one transaction, advisory lock) | Classes → users; transparent **fit score**; insert new matches, update changed ones, supersede lost ones. | matches |
| **Proof before writing** | B1 · SQL + IF gate | Before Stage 3: the class decisions expanded to users vs a naive evaluation of **every** pair. A mismatch stops the run with zero matches written. | pairs |
| **Proof after writing** | B1 · SQL + IF gate | After Stage 3: the stored matches vs the naive evaluation again (also checks Stage 3's diff). A mismatch stops the run before emails. | pairs |

![Treasure Hunt funnel](docs/treasure_hunt_funnel.svg)

The figure is generated from the evidence file by [`scripts/funnel_svg.py`](scripts/funnel_svg.py) (CI fails if it is stale).

### Measured funnel (`pipeline_runs`, run on RDS with the real `users.csv`; raw export and query in [`docs/evidence/`](docs/evidence/))
| | |
|---|---|
| Users × active products | 10,000 × 59 |
| **Naive pairs (what a brute-force LLM would see)** | **590,000** |
| Equivalence classes | **164** |
| Class × product decisions | **9,676** (1.6% of the naive pairs) |
| User-product pairs passing the hard criteria | 276,594 |
| Decided by SQL rules / by LLM-compiled rules | 467 / 3,741 class-product pairs |
| Distinct free-text criteria → **LLM calls** | 46 → **5 calls** (7,008 input + 5,847 output tokens, **≈ $0.024**¹) |
| Matches written | 276,594 |
| **Correctness proof** (naive re-evaluation of all 590,000 pairs) | ✅ **0 mismatches** |
| Duration | 40 s |
| **Next runs** (criteria cached) | **0 LLM calls, $0.00** |
| Live demo upload (6 new users) | 354 naive pairs → 6 classes → 0 LLM calls → 195 matches → 5 emails, a few seconds after upload |
| **Product mode** (daily crawl changed 11 products → A calls B automatically) | 10,006 users × 11 products = 110,066 naive pairs → 18 classes → 1 LLM call → 3,241 new / 4,946 superseded matches → ✅ 0 mismatches → 5 emails, 36 s |

**Re-run after a correctness fix (2026-10-10):** an independent review of the numbers found that
a lender publishing **no** criteria was counted *eligible* (Federal Bank on Paisabazaar: 10,000
of 10,000). Our normalizer marks such products "criteria not published: confirm with the lender",
but `compile.js` dropped that note, leaving no rules and no requirements. The note is now always a
requirement (*may qualify*), the cached compile results were corrected by migration 007, and the
same 10,000 users were re-matched through the normal sweeper path: run `80864307`, 580,000 pairs
(58 active products), 164 classes, **0 LLM calls** (44 cached answers), proof **0 mismatches**.
Eligible users per lender then matched an independent recomputation from `users.csv` for every
lender ([evidence](docs/evidence/README.md)).

¹ Estimated at Bedrock's Nova Pro list price ($0.0008 / $0.0032 per 1k tokens); Sydney pricing may differ slightly.

**Why classes are exact:** for any cut point *c*, `value ≥ c` ⇔ `floor(value) ≥ c`, where
`floor(value)` is the largest cut ≤ value. Every comparison the rules make is against a cut,
so the floor answers exactly like the real value. Fixed bands (e.g. "₹25–50k") would be wrong:
users at ₹26k and ₹45k differ for a ₹30k product. The integration test adds compiled rules with
awkward thresholds (742, ₹99,999, age 30) and still gets **0 mismatches** against brute force.

**Why it scales (measured):** LLM cost is tied to *distinct criteria texts* (46), not to users
or pairs. The class count is bounded by the cut points, not by users. The real matching SQL, run
locally on synthetic users with the same product snapshot
([`scripts/bench_matching.py`](scripts/bench_matching.py), raw output in
[`bench_matching_2026-10-11.json`](docs/evidence/bench_matching_2026-10-11.json)):

| Users | Naive pairs | Classes | Class × product decisions | LLM calls | Stage 1+2 | Full match run (both proofs) |
|---|---|---|---|---|---|---|
| 10,000 | 590,000 | 329 | 19,411 | 0 | 0.1 s | 5.3 s, 0 mismatches |
| 100,000 | 5,900,000 | 360 | 21,240 | 0 | 0.4 s | 88 s, 0 mismatches |
| 1,000,000 | 59,000,000 | **360** | **21,240** | 0 | 3.1 s | not run (see below) |

Ten times the users from 100k to 1M: the same 360 classes and 21,240 decisions. The
benchmark uses only 3 compiled rules, so it has more classes than the live run's 164; the point
is the growth. What does grow with users is writing the matches (Stage 3) and the two
every-pair proofs. At 1M users that is about 27 million match rows, past n8n's 10-minute
execution limit on this setup. The production step is in §11: Stage 3 in user-id chunks and a
sampled proof above a size threshold.

**What the LLM changes (measured on the reference run, [evidence](docs/evidence/LLM_IMPACT.md)):**
the compiled rules decide 85% of the class × product pairs that pass the hard criteria.
- **3,240 became "may qualify"** with the lender's own requirement, for example "minimum 2 years of
  ITR returns".
- **13 were rejected.** ICICI Bank's page says self-employed applicants must be **28+**, which the
  structured minimum age missed. The rule `age ≥ 28 (self-employed)`, stored with that quote,
  removed an offer 377 users could not get.

**Fit score (ranking, not prediction):** 0–100 = tier (eligible 60 / conditional 35) + income
headroom (≤ 15) + credit margin (≤ 10) + rate (≤ 15). Every term traces back to a published
lender rule, and the email explains it ("your income is 3.6× the minimum"). We did not train a
model: there is no approval/outcome data, so the system reports **indicative eligibility from
published criteria**, never an approval probability.

![B1 funnel output](docs/screenshots/12-B1-funnel-output.png)

---

## 9. Failure handling

| Failure | What happens | Where |
|---|---|---|
| Duplicate S3/SQS delivery | `FOR UPDATE SKIP LOCKED` on the job → second delivery is a no-op | ingest |
| Malformed CSV (missing column, not UTF-8) | Job `FAILED` immediately with a clear error, no retries | ingest |
| Bad rows | Stored in `upload_rejects` (line + reason), shown in the UI; good rows load | ingest |
| Transient error (DB blip, S3) | Re-raised → SQS retries (720 s); on the 3rd attempt the handler marks the job `FAILED` (visible in the UI) and consumes the message | ingest + SQS |
| Hard crash (timeout, DB unreachable before the claim) | SQS moves the message to the DLQ after 3 receives; the **`ingestDlq` Lambda** marks the job `FAILED` with "upload the file again" (the UI no longer shows "retrying" forever) and a **CloudWatch alarm** on its invocations emails the operator | SQS + Lambda + CloudWatch |
| Two uploads sharing users at the same moment | The upsert locks rows in `user_id` order, so they can never deadlock (a concurrency test reproduced the deadlock before the fix) | ingest |
| Huge file | Rows stream through `COPY`; memory stays flat (measured on 50 MB) | ingest |
| File never uploaded | Ticket shows `EXPIRED` after 15 min | api |
| n8n down / webhook lost | Ingest still completes; B's **10-minute sweeper** picks the job up | B |
| Duplicate webhook / sweeper race | Atomic claim: only one run per job | B |
| Matching run crashes | Job `FAILED` (UI); a stale lock (> 15 min) is reclaimed by the sweeper | B |
| A wrong class decision | The pre-write proof stops the run before Stage 3: zero matches written, job `FAILED`, E alerts | B1 |
| Criteria that failed to compile earlier | Counted as "may qualify" (never wrongly eligible); once compiled, every user is re-matched against those products | B |
| LLM error / throttling / malformed output | Retries; the shared parser ([`structured.js`](n8n/code/structured.js)) tolerates fences/prose, normalizes placeholders like `"null"`, and never throws; affected pages keep their existing products and are retried next run | A1, B1 |
| LLM hallucination | Evidence verification on every extracted number, and every listed condition is checked against the page: a phrase not found there is shown as "also mentioned, not verified" and is never compiled into a rule, so it can never reject anyone | A1, B1 |
| Site down | S3 fixture used, `crawl_runs.status = fixture` | A1 |
| Site blocks bots / robots.txt says no | Skipped and logged (`blocked` / `robots_disallowed`), never bypassed | A, A1 |
| Site layout changes | No section found → page `failed`, existing products kept (not wiped); a channel whose usable pages drop by more than 30% raises a crawl-health alert (once a day) | A1, A |
| Same CSV uploaded again | 0 inserted, 0 new matches, 0 emails (verified live) | ingest + B |
| User no longer qualifies | Match `superseded` (history kept), no email | B1 |
| SES send fails | Retried twice in the node; then recorded as `failed` and the match stays un-notified, so re-running C for that run sends it | C |
| n8n dies in the middle of the send loop | Each send was recorded as it happened: the re-run sends only the remainder, nobody twice (tested) | C |
| n8n loses its database between matching and email | B's sweeper finds runs with matches but no email record, **re-runs the proof**, and lets C finish them. Found live when one run's screen waited for emails forever; it was recovered this way | B, C |
| A busy database during a 10k run | n8n keeps 6 pooled connections with a 60 s connect timeout (it lost its database once on the default 2 and 20 s). The api reuses one connection per container and retries connects 3 × 8 s within a 28 s limit. Live load test, two uploads at once with the console polling: before, 4 × 503 and n8n connection errors; after, **0 errors** (52 of 52 requests OK) and both runs finished with emails | n8n, api |
| A statement that outlives its execution | Postgres ends n8n statements after 10 minutes (n8n's own limit) and closes idle-in-transaction sessions | RDS |
| Deleting a 10,000-customer upload | Deleted in chunks of 2,000 per short transaction; each call stops after ~15 s and reports what is left, and the console continues until done (one big transaction passed the API limit on the 1 GB database and rolled back; found live) | api, console |
| The shared demo database filling up | After a run completes (matched, proved, emails recorded) and its charts load, the console asks once to **delete that upload's records**, giving the reason (AWS free plan: one 1 GB RDS shared by every reviewer). The analytics stay on the page: a snapshot is taken just before the delete and shown afterwards, marked as kept | console, api |
| An upload you want to stop | **Stop** in the console: before its file is loaded it is cancelled for real (a later delivery of the file is ignored); once matching runs in n8n it finishes on its own and Stop just ends the tracking (delete the upload afterwards) | api, console |
| Reload or a network blip during an upload | The console keeps tracking the same job after a reload; transient errors show "reconnecting" while polling continues; the charts retry by themselves | console |
| Email or error text with newlines | Passed to Postgres as one JSON parameter (n8n's plain parameters broke on it; found live, fixed, guarded by a test) | C, E |
| Any workflow fails | Error workflow **E**: `workflow_errors` row + rate-limited alert email | E |
| Run dies mid-way (n8n restart) | Sweeper closes runs `running` > 30 min; a re-claimed job closes its old run | B |
| Malformed webhook body | Non-UUID `job_id` dropped before SQL (the header secret is checked first) | B |
| Product with no rule on a dimension | Stored as an empty cut list, not JSON `null` (found by the product-mode test) | B1 |
| Planner misestimates after bulk writes | `ANALYZE` step between Stage 1 and Stage 3 (found in testing: 7 min → seconds) | B1 |

---

## 10. Security

- **Nothing is reachable from the internet except** the throttled HTTP API and S3 presigned POSTs
  (key-pinned, `text/csv`, ≤ 50 MB, 10-minute expiry). RDS, Lambdas and n8n have no inbound internet access.
- **No SSH anywhere.** The n8n editor and RDS are reached through **SSM port forwarding**.
- **No long-lived AWS keys.** n8n uses its EC2 instance role → assumes `loan-engine-dev-n8n-aws`
  (SES send + Nova Pro invoke + read fixtures only), with an External ID.
- **Secrets only in Secrets Manager**, generated at deploy time; never in code, user-data, `.env`
  files in git, or workflow exports. n8n encrypts its credentials with a retained key.
- **TLS verified to RDS everywhere** (`rds.force_ssl=1`): n8n checks the AWS RDS CA bundle, and the
  Lambdas connect with `sslmode=verify-full` against the RDS ap-southeast-2 CA bundle shipped in
  their package (tests and CI keep `require` for their self-signed Postgres).
- **Accounts own their data:** every `/uploads` route is behind the Cognito JWT authorizer, and the
  Lambda checks ownership again (owner or admin, otherwise 404). An upload's analytics come from
  `GET /uploads/{job_id}/analytics` on the same rule. The public `/analytics` serves only the
  operator's reference dataset (the largest upload owned by an admin, never another merchant's).
  The public `/ops/runs` hides the `job_id` of merchant-owned runs.
- **Abuse limits:** 10 uploads per account per day (under a global 50), 20 instant checks per
  visitor per day (under a global 100). A visitor is identified by an HMAC of the source IP keyed
  with a Secrets Manager key; the raw IP is never stored.
- **Sign-in:** Cognito email + password (codes from Cognito) or Google (OAuth code flow with PKCE).
  Sign-out revokes the refresh token and ends Cognito's session; Google always shows its account
  chooser (`prompt=select_account`, managed login).
- **Least-privilege Postgres roles:**

| Role | Used by | Can |
|---|---|---|
| `dbadmin` (RDS-managed, rotating) | migrate Lambda only | everything (migrations) |
| `app_ingest` | api, ingest | read/write `upload_jobs`, `users`, `upload_rejects`; read progress tables |
| `n8n_workflows` | n8n Postgres credential | read users; update **only** the match-progress columns of jobs; read/write crawl + matching tables; ANALYZE (PG17 `MAINTAIN`) its bulk tables. **No DELETE, no DDL.** |
| `n8n_meta` | n8n's own storage | owns database `n8n` only; cannot connect to `app` |

- **Email safety:** mail goes only to verified test aliases (code guard + SES sandbox as a second guard).
- **Crawled content is untrusted:** HTML-escaped in emails; the optional renderer refuses private/metadata IPs.
- **Raw uploads are deleted after 7 days** (S3 lifecycle); the bucket blocks public access and denies non-TLS requests.

---

## 11. Trade-offs & production next steps

- **Region:** the account's AWS Organization blocks every region except Sydney. Production for
  Indian borrowers would run in **`ap-south-1` (Mumbai)** for data residency.
- **SES sandbox + Gmail sender:** fine for the demo (mail may land in Spam because of gmail.com's
  DMARC policy). Production: SES production access, a verified domain with DKIM/SPF/DMARC.
- **Demo cap:** 5 real emails per run; production removes the cap and sends at the account's SES rate.
- **n8n editor via SSM only:** production would put it behind an ALB + ACM + SSO.
- **Single-AZ RDS `db.t4g.micro`:** production: Multi-AZ, larger instance, automated rotation for app roles.
- **Very large files:** ingest streams at flat memory: 10,000 rows took 1.1 s live, and 50 MB
  (520,000 rows) took 15.8 s locally. Beyond about 1 GB: S3 byte-range chunking with one SQS
  message per chunk, or Step Functions Distributed Map.
- **Matching at a million users:** classes stay bounded (measured, §8), but writing ~27 million
  matches and proving every pair would pass n8n's 10-minute limit. The next step is Stage 3 in
  user-id chunks and a sampled proof above a size threshold (the full proof stays at 10k).
- **Upload API:** sign-in and per-account quotas are in place; production adds an AWS WAF rate rule.
- **Sign-in emails:** Cognito's own sender has a daily quota. Production sends them through SES
  with a verified domain.
- **Crawler:** crawl-health alerting is in place; next, enable the renderer per source where allowed.
- **LLM quality:** the LLM's effect is measured ([evidence](docs/evidence/LLM_IMPACT.md)), its
  accuracy is not. That needs a gold set of criteria labelled by a person, scored for rule
  precision and recall per model (Nova Pro vs Lite).

### Measured cost

From AWS Cost Explorer, usage before credits, 2026-10-07 to 10-10
([raw export](docs/evidence/cost_2026-10-11.json)). All of it was covered by account credits.

| Item | So far | Why it costs |
|---|---|---|
| VPC interface endpoint (Secrets Manager, 2 subnets) | $1.14 | billed per endpoint-hour, used or not |
| RDS `db.t4g.micro` + 20 GB gp3 | $1.25 | always on |
| Public IPv4 addresses | $0.52 | two addresses: n8n's egress IP, and probably the unrelated instance below |
| Amazon Bedrock · Nova Pro | $0.47 | every crawl extraction and criteria compile since day one, including development |
| EBS, Secrets Manager, SES, S3, API Gateway, Lambda | $0.34 | small |
| n8n EC2 `t4g.small` | $0.00 | EC2 free trial for t4g.small |
| **Total in Cost Explorer, minus the unrelated instance** | **$3.73** | |

These figures leave out $0.64 for an EC2 `t4g.micro` named "recover" in the same account. It is
not part of this stack (no CloudFormation tag).

**Steady state**, from the billed hourly rates: the endpoint is about $0.62 a day and RDS about
$0.60. One IPv4 address, storage and secrets add about $0.20. That is roughly **$1.40 a day
(≈ $43 a month)**, plus Nova Pro only when pages or criteria change.

- **Per 10,000-user run:** about $0.024 of LLM on the first run, then **$0.00**, because criteria
  texts are cached. Compute is seconds on resources that are always on anyway.
- **Per daily crawl:** $0.00 of LLM when no page changed. Only changed pages reach Nova Pro.
- **Cheaper options, not taken:** the interface endpoint is the biggest fixed cost. Dropping it
  needs a NAT gateway, which costs more and opens the private subnets to the internet. RDS could
  move to Aurora Serverless v2 with scale-to-zero, but cold starts would slow the first upload.

---

## 12. Code quality & tests

- **Python 3.12**, type hints everywhere, small pure functions with I/O at the edges, docstrings
  and comments that explain *why*; **ruff** (lint + format) clean.
- **359 Python tests, 0 skipped** (308 unit, 51 integration), **92% line coverage** of
  `loan_engine` (CI fails below 90%), and **mypy** clean:
  - unit tests
  - **workflow lint**: every connection resolves, no orphan nodes, every workflow reports to E,
    sub-workflow ids exist, webhooks are authenticated, credentials are references only,
    **no secrets** in the exports, and every Code node compiles
  - **51 integration tests** against a real Postgres 17 with TLS:
    - **The ingest path.** 10k users (the real CSV locally; a deterministic synthetic twin in
      CI, since the real file is never committed). Every ingest test runs on **both** ingest
      paths. The memory test shows the streaming path stays flat on 100,000 rows.
    - **The Treasure Hunt** in upload and **product** mode, with both proofs. A test corrupts one
      class decision and checks that the pre-write proof stops it before any match is written.
    - **Concurrency.** A duplicate delivery, two uploads sharing users (this test found a real
      deadlock), and the webhook racing the sweeper for one job.
    - **The golden master** ([`test_golden.py`](tests/integration/test_golden.py)). An
      order-independent fingerprint of ingest counts, reject reasons and every match, which may
      only change in a commit that says why. It also checks that re-uploading the same file
      changes nothing.
    - **Workflow C's SQL.** A crash after 2 of 5 sends leads to only 3 more; C1 builds every
      skipped user's email and its loop ends.
    - **Independent recompute.** [`scripts/recompute_eligibility.py`](scripts/recompute_eligibility.py),
      plain Python with no SQL, agrees with the analytics chart.
    - **The rest:** the crawl-health alert, account isolation and the reference dataset, the data
      reset run as the least-privilege api role, and upload ownership.
- **52 Node tests** for the n8n Code-node logic (including a snapshot of Workflow C's email text) (`node --test n8n/code/code.test.js`); the same files are
  what runs inside n8n.
- **CI** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs three jobs on every push:
  - `test`:
    1. ruff and mypy;
    2. the funnel figure must match its evidence file;
    3. the Node tests;
    4. the Python unit and integration tests with coverage, on a Postgres 17 container with TLS;
    5. the golden master again on the streaming ingest path;
    6. the committed workflow JSON must equal the generator's output.
  - `dashboard`: typecheck, 24 tests, build.
  - `web`: lint, typecheck, 44 tests, build.

  ![CI](docs/screenshots/18-github-ci.png)
- Structured JSON logs (AWS Lambda Powertools) carrying `job_id`.

```bash
.venv/bin/ruff check . && .venv/bin/pytest && node --test n8n/code/code.test.js
# DB integration tests (need Docker):
docker run -d --rm --name pgtest -e POSTGRES_PASSWORD=localtest -e POSTGRES_DB=app -p 55432:5432 postgres:17 \
  -c ssl=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key
PG_TEST_PORT=55432 .venv/bin/pytest tests/integration
```

---

## 13. Repository layout

```
serverless.yml              all AWS resources (VPC, endpoints, RDS, S3, SQS, Lambdas, API, EC2, IAM, secrets)
docker-compose.yml          n8n (+ optional renderer, + local Postgres profile)
deploy/n8n/boot.sh          idempotent EC2 bootstrap (Docker, secrets → .env, start n8n)
loan_engine/                Python Lambdas: api/ (FastAPI + Mangum), ingest/ (+ dlq.py), migrate/, common/ (validation, db + RDS CA, secrets, notifier)
sql/                        001–012 migrations, R__grants.sql (least privilege), matching/ (the SQL of Workflows A, B, C)
n8n/workflows/              the workflow exports A, A1, B, B1, C, C1, E, E1 (generated)
n8n/code/                   Code-node logic (tested with node --test)
n8n/prompts/                versioned LLM prompts
n8n/build_workflows.py      generates the workflow JSON from the tested sources
dashboard/                  the app at /app (React; built into loan_engine/api/static/)
web/                        the landing page at / (Vite + TS + three.js; built into loan_engine/api/site/)
renderer/                   optional headless renderer (Playwright, SSRF guard)
scripts/                    tunnels, n8n import/run, psql, upload sample; recompute_eligibility.py, bench_ingest.py, bench_matching.py, funnel_svg.py
tests/                      unit + integration tests, fixtures
.github/workflows/ci.yml    CI: ruff, mypy, JS + Python tests with coverage, Postgres integration (both ingest paths), generator + figure checks
docs/                       evidence (live checks, measurements, cost), screenshots, EXTRAS.md, funnel figure
PLAN.md                     the build plan + decision log
```

---

## 14. Extra: landing page, app and accounts (one product)

Beyond the assignment, the same api Lambda serves a landing page (`/`), the **merchant console**
(`/app/merchant`: the upload UI, plus analytics and a single-customer lookup), a borrower
dashboard that the email's **View all N matches** button opens, and Cognito accounts (email +
password or Google). Uploads require sign-in and belong to the account: each reviewer starts
with an empty workspace and sees only their own uploads. Details, routes and the data-reset
rules: [`docs/EXTRAS.md`](docs/EXTRAS.md).

![Borrower dashboard](docs/screenshots/15-dashboard.png)
