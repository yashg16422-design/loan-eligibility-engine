# Extras: landing page, app and accounts (one product)

Everything here is beyond the assignment; the required path is in the [README](../README.md).
The upload UI the assignment asks for is the merchant console's *Bulk upload*.

One origin serves everything from the api Lambda (no extra hosting, no CORS):

| Path | What | Built from |
|---|---|---|
| **`/`** | The **ClickPar Match** landing: the scroll story (globe → India → Surat, the problem, the team, Aarav's journey, the engine, proof) | [`web/`](../web/) (Vite + TypeScript + three.js) |
| **`/app/merchant`** (also `/app/`) | **Merchant console** (sign-in required to upload; the landing's top bar has *Merchant login*): **Workspace** with two tools, *Bulk upload* (CSV → the **live pipeline**: Upload → Validate and load → Workflow B → Workflow C, with rows and funnel charts forming as the run reports) and *Single lookup* (one customer's four numbers → their full results) → **Metrics** shown by default (your customers, matches, emails; lender products, pairs, classes, AI calls, proof) → **Analytics** of any dataset you pick (your uploads, or the 10,000-user reference) → **History & runs** behind expand rows: your uploads (View / Delete), matching runs, Workflows A/B/C/E with retries and errors | [`dashboard/`](../dashboard/) (React + Tailwind) |
| **`/app/check`** | One person's check: a 1-row CSV through the **same** pipeline (≈ 11 s live) | |
| **`/app/dashboard`** | Results in order: **Top 5** (best pick first) → **Also eligible** → **May qualify** → **Not eligible, with the exact published rule missed** → **Quick tips** (exact score/income thresholds that open more lenders); **What if** (mirrors Workflow B's decision, tested on all 59 live products) and **Compare** (EMI, total interest) alongside | |
| **`/app/account`** | **Accounts (Amazon Cognito)**: sign up with email + password, confirm with the emailed code, sign in from any device; saved checks; daily top picks | |
| **`/upload`** | Redirects to the merchant console (uploads now need an account) | |

**Accounts:** sign up with email + password (confirmed by an emailed code), **forgot / reset
password** (emailed code), or **Continue with Google** (Cognito's OAuth 2.0 authorization-code
flow with PKCE through the managed-login domain; Google's client secret is a Secrets Manager
dynamic reference, never in the repo or the template; switched on with `GOOGLE_SIGN_IN=true`
once `loan-engine/<stage>/google-oauth` exists). One account per verified email: a password
sign-up and a Google sign-in with the same address resolve to the same account row, so uploads
and saved checks follow the person. Cognito owns identity (passwords never reach our code or database). Its default
email sender delivers verification codes to **any** address, which our own SES cannot do while
in the sandbox. API Gateway's **JWT authorizer** verifies the Cognito ID token on every
`/account` route before the Lambda runs (verified live: no token or a fake one → 401).
Google always shows its account chooser (managed login forwards `prompt=select_account`), and
sign-out revokes the refresh token and ends Cognito's one-hour session. A Google-only account
has no password: the reset screen says so (Cognito deliberately sends nothing, to avoid
revealing which emails exist) and offers Google, or adding a password with the same email. Our
database stores `accounts` (Cognito `sub`, email, daily-picks flag) and `account_profiles`
(which checks an account saved; whoever saves a check first owns it, enforced by a UNIQUE key).
Saving needs the results link, proving the person ran (or was emailed) that check.

**From the email to the dashboard:** every notification email carries a **"View all N
matches"** button: Workflow C asks the api Lambda to sign one 14-day link per user (verified
live: check → matches → `email tokens signed count=1` → 1 email with the button).

**Every account starts fresh:** an owned upload's customers get account-scoped ids (UUIDv5 of
account + CSV `user_id`), so the same file uploaded by a second reviewer loads as new customers
and runs the whole pipeline (match, proof, emails), while the same account re-uploading it is
still idempotent. Signed in, the console shows only your uploads, metrics and analytics (an
empty state before the first upload); *Reset my workspace* deletes all your uploads' customers
(`DELETE /uploads`), and admins can clear every account (`DELETE /uploads?scope=all`).

**Uploads belong to accounts (migration 008):** every `/uploads` route is behind the Cognito JWT
authorizer; `POST /uploads` stamps the job with the account, and `GET /uploads`,
`GET /uploads/{job_id}` and `DELETE /uploads/{job_id}` answer only for the owner (or an admin;
anyone else gets a 404, so other merchants' uploads are not even confirmed to exist). Upload
progress includes rejected raw lines, which can hold personal data: that is why it is
owner-only. `GET /uploads` lists the account's uploads as records (file, time, rows new /
changed / rejected, customers still in the database, matches, emails; counts only); each row
has *View* (its own charts) and *Delete*. The default charts show the upload with the most users,
and the runs list always includes the full-file reference run, so test runs or a reset never
hide the measured Treasure Hunt numbers.

**Data reset (start again without touching accounts):**

| Who | Where | What is deleted | Route |
|---|---|---|---|
| A person | My matches → *Start over* | their own instant check (only instant checks; a link can never delete bulk-upload data) | `DELETE /me` (dashboard token) |
| A signed-in account | Account → *Remove* / *Start fresh* | its saved checks: its own instant checks are deleted, a saved bulk-upload profile is only unlinked; the account and its settings stay | `DELETE /account/profiles[/{user_id}]` (Cognito) |
| The uploading merchant | Merchant console → History & runs → **Your uploads** → *Delete* | that upload's customers, so the same file can be uploaded again and run as a new record (B matches, C emails) | `DELETE /uploads/{job_id}` (Cognito, owner) |
| An admin | Same table (an admin sees every account's uploads) → *Delete*, or *Delete all uploaded users* | any upload's customers, or every customer that came from a CSV | `DELETE /uploads[/{job_id}]` (Cognito + `admin` group) |

Matches, email records, preferences and account links go with each user by `ON DELETE
CASCADE` (migration 006 adds the `user_id` indexes that keep this an index lookup per user).
Lender products, `pipeline_runs` (the Treasure Hunt evidence) and the job rows are never
deleted; a cleared upload is stamped `purged_at` and shows *data deleted* in recent runs. A job
that is still loading, matching, or inside the 2-minute window in which Workflow C emails is
refused (409), and its row is locked during the delete. Tested
against real Postgres as the least-privilege `app_ingest` role
(`test_data_reset_runs_as_app_ingest_and_keeps_history`).

Admin membership is never self-service. After signing up in the app, add yourself once:

```bash
aws cognito-idp admin-add-user-to-group --region ap-southeast-2 --user-pool-id "$(scripts/stack-output.sh UserPoolId)" --username you@example.com --group-name admin
```

Sign out and in again so the new ID token carries the group.

**Design:** monochrome studio chrome (true black, white type, grey hairlines, light Inter
display, tracked JetBrains Mono for data labels, a white primary button) with colour only where
it carries data: green eligible, amber may qualify, red not eligible, violet for the engine,
blue / teal / indigo for who the customers are. Progressive disclosure: metrics and analytics
by default, history, runs and retries behind expand rows; long result lists on *My matches*
collapse with their counts visible. Documented in [`dashboard/DESIGN.md`](../dashboard/DESIGN.md).
No decorative motion: bars move only when their numbers change.

![Borrower dashboard](screenshots/15-dashboard.png)
![Compare view](screenshots/16-dashboard-compare.png)
![Overview](screenshots/17-engine.png)

```bash
scripts/build-frontends.sh   # web/ -> loan_engine/api/site/, dashboard/ -> loan_engine/api/static/
serverless deploy            # ships both inside the api Lambda
```
