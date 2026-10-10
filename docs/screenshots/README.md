# Screenshots

Save each file **here** with the exact name; README.md already links every one of them.
Mac: `Cmd+Shift+4`, then `Space`, then click the window. Browser window about 1440 px wide.
Before each capture, check that **no secret value is visible**: n8n masks credential fields, so never click
"show" on a password.

Text proof of the same things (n8n execution log, DB rows, CI) is in
[`docs/evidence/REQUIRED_PATH.md`](../evidence/REQUIRED_PATH.md).

## A. Required by the assignment (capture these first)

Open n8n first. In one terminal run `scripts/tunnel-n8n.sh`, then open http://localhost:5678 and sign in.

| # | File | Where | Must be visible | Proves |
|---|---|---|---|---|
| 1 | `01-upload-ui.png` | `/app/merchant`, signed in, after **Upload CSV** with `users.csv` | The four pipeline boxes done, rows in / matched / emailed | Upload UI → S3 → Lambda → RDS → n8n |
| 2 | `02-n8n-workflows.png` | n8n Overview | A, A1, B, B1, C, E, E1 listed with published toggles | Self-hosted n8n with all workflows |
| 3 | `03-cred-postgres.png` | Credentials > **RDS app (n8n_workflows)** | Host, database `app`, user `n8n_workflows`, SSL on; password masked | Database credential in n8n |
| 4 | `04-cred-aws-assume-role.png` | Credentials > **AWS n8n role (assume)** | Assume Role, role ARN, external ID; no access keys | AWS credential in n8n |
| 5 | `05-cred-header-auth.png` | Credentials > **Ingest webhook secret** | Name `X-Webhook-Secret`; value masked | Secured webhook |
| 6 | `06-credentials-list.png` | Credentials list | The three credentials | |
| 7 | `07-workflow-A.png` | Workflow A canvas (Shift+1 = zoom to fit) | Schedule + manual trigger, robots, hubs, batching, Finish run | Workflow A |
| 8 | `08-workflow-A1.png` | Workflow A1 canvas | Fetch, classify, hash, Changed?, Nova call, upsert | Crawler internals |
| 9 | `09-workflow-B.png` | Workflow B canvas | Webhook, sweeper, product-mode trigger, claim, B1, C | Workflow B trigger |
| 10 | `10-workflow-B1.png` | Workflow B1 canvas | Compile, Stage 1+2, ANALYZE, Stage 3, proof, finish | Treasure Hunt |
| 11 | `11-workflow-C.png` | Workflow C canvas | Users to email, Sign links, Compose, SES loop, Record | Workflow C |
| 12 | `12-B1-funnel-output.png` | B1 > Executions > the newest 10,000-user run > **Treasure Hunt funnel** node > Output | users 10000, pairs 580000, classes 164, mismatches 0 | Treasure Hunt numbers |
| 13 | `13-workflow-E.png` | Workflow E canvas | Error Trigger, Record error, Alert due?, SES | Failure handling |
| 14 | `14-email.png` | Gmail, the newest "you may qualify" email | Top picks with "why", **View all N matches** button, the To: `+alias` | Email received in test inbox |
| 15 | `18-github-ci.png` | GitHub > Actions > latest run on `main` | All jobs green | Code quality |

For 12: n8n keeps executions, so the 13:46 UTC run on 2026-10-10 (the `users.csv` upload) should still be
listed. Any upload run's funnel node shows the same fields.

## B. Extras (after A is done)

| File | Where | Must be visible |
|---|---|---|
| `15-dashboard.png` | Click **View all matches** in the email, or run a check at `/app/check` | Summary, top picks, What if (captured) |
| `16-dashboard-compare.png` | Same page: add 2 or 3 offers to Compare | EMI, total interest, "costs less" line (captured) |
| `17-engine.png` | `/app/merchant`, signed in > Analytics | Charts, plus "Emails sent for this upload" opened |
| `x1-landing.png` | `/` | Landing hero (already captured) |
