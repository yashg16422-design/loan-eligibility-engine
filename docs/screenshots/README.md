# Screenshot checklist (capture once, in this order)

Save each file **here** with the exact name; the main README already links them.
Mac: `Cmd+Shift+4`, then `Space`, then click a window (or drag a region). Use a browser
window about 1440 px wide. Before each capture: **no secret values visible** (n8n masks
credential fields; never click "show" on a password).

Open n8n first: `scripts/tunnel-n8n.sh`, then http://localhost:5678.

| # | File | Where | Must be visible |
|---|---|---|---|
| 1 | `01-upload-ui.png` | https://t7lcgp5o0j.execute-api.ap-southeast-2.amazonaws.com/ after uploading `tests/fixtures/demo_users.csv` | All four steps finished, the funnel line, the rejected row |
| 2 | `02-n8n-workflows.png` | n8n home (Overview) | A, A1, B, B1, C, E, E1 listed, published toggles |
| 3 | `03-cred-postgres.png` | n8n > Credentials > "RDS app (n8n_workflows)" | Host, database `app`, user `n8n_workflows`, SSL; password masked |
| 4 | `04-cred-aws-assume-role.png` | Credentials > "AWS n8n role (assume)" | Assume Role, role ARN, external ID; no access keys |
| 5 | `05-cred-header-auth.png` | Credentials > "Ingest webhook secret" | Name `X-Webhook-Secret`; value masked |
| 6 | `06-credentials-list.png` | Credentials list | The three credentials |
| 7 | `07-workflow-A.png` | Workflow A canvas (zoom to fit) | Schedule + manual trigger, robots, hubs, batching, Finish run, product-mode call to B |
| 8 | `08-workflow-A1.png` | Workflow A1 canvas | Fetch, classify, hash, Changed?, Nova call, upsert |
| 9 | `09-workflow-B.png` | Workflow B canvas | Webhook, sweeper, product-mode trigger, claim, B1, C |
| 10 | `10-workflow-B1.png` | Workflow B1 canvas | Compile, Stage 1+2, ANALYZE, Stage 3, proof, finish |
| 11 | `11-workflow-C.png` | Workflow C canvas | Users to email, Sign dashboard links, Compose, SES loop, Record |
| 12 | `12-B1-funnel-output.png` | B1 > Executions > the 10k run > "Finish run" node output | users_in 10000, naive_pairs 590000, classes 164, correctness_ok true |
| 13 | `13-workflow-E.png` | Workflow E canvas (or its execution of the E1 drill) | Error Trigger, Record error, Alert due?, SES |
| 14 | `14-email.png` | Gmail, the newest "you may qualify" email | Best pick, top picks with "why", the **View all N matches** button, the To: alias |
| 15 | `15-dashboard.png` | Click that button (or /app/ after a check) | Summary sentence, one row expanded ("Why it fits"), What if panel |
| 16 | `16-dashboard-compare.png` | Same page: compare 2-3 offers, scroll to Compare | EMI, total interest, "costs less" line, checklist |
| 17 | `17-engine.png` | /app/ops | The pipeline (5,90,000 pairs > 164 classes > 5 AI calls), recent runs |
| 18 | `18-github-ci.png` | GitHub > Actions > latest run | Both jobs green (test, dashboard) |

Tip for 12: if the 10k run's execution is gone, any upload run's "Finish run" output shows
the same fields; the README's measured numbers come from `pipeline_runs`.
