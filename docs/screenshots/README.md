# Screenshots

The assignment does not ask for screenshots: it asks for the README (architecture diagram, setup
including the n8n credentials, design decisions), the workflow JSON and the video. The proof of
every required path is written down in [`docs/evidence/REQUIRED_PATH.md`](../evidence/REQUIRED_PATH.md)
(n8n execution log, RDS rows, emails, CI), and the video shows the rest live.

These captures support the README sections that link them:

| File | Shows | README section |
|---|---|---|
| `06-credentials-list.png` | The three n8n credentials: Postgres (`n8n_workflows`), AWS Assume Role, webhook Header Auth. No secret values | Configuring credentials inside n8n |
| `09-workflow-B.png` | Workflow B: webhook, 10-minute sweeper (with the email-recovery branch), product mode, claim, B1, C, late-compile re-match | Workflows |
| `10-workflow-B1.png` | Workflow B1 (the Treasure Hunt) with its succeeded executions | Workflows, §8 |
| `15-dashboard.png`, `16-dashboard-compare.png` | Borrower dashboard and offer comparison | Extras |
| `x1-landing.png` | Landing page | Extras |

Before adding one: check that no secret value is visible (n8n masks credential fields; never click
"show" on a password) and crop the browser's tab bar.
