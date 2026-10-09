# Extras spec: product landing, borrower dashboard, ops console

This is the brief for building the **frontend** of the Loan Eligibility Engine as a real product.
The backend (AWS + n8n + the Treasure Hunt) is **built, deployed and verified live**. Do not
change it. Read `CLAUDE.md`, `README.md` and `PLAN.md` first: they explain what the system
does, the measured numbers, and the house rules.

**Creative freedom:** this brief sets the goals, the data and the boundaries. Inside them,
use your own judgement for the best possible result: art direction, motion, copy, component
design, information architecture. Propose better ideas than the ones written here when you
have them. Stay consistent with the repository's quality bar (typed code, small components,
comments that explain *why*, tests for logic, no secrets).

---

## 0. Ground rules (non-negotiable)

1. **Work on the branch `ui`**, in a new top-level folder **`web/`**. Open a pull request to
   `main` when done. Do not modify `loan_engine/`, `sql/`, `n8n/`, `serverless.yml`,
   `deploy/`, `docker-compose.yml` or `scripts/`. Backend changes are made in a separate session
   that has AWS access.
2. You have **no AWS access** and need none. Build against the mock data in
   [`docs/extras/mock/`](extras/mock/): it is a real export from the live database (2
   synthetic demo users, their 69 real matches, the 59 real crawled products, the real
   pipeline runs). Copy it into `web/public/mock/`.
3. **CI must stay green.** `ruff`, `pytest` and `node --test n8n/code/code.test.js` must still pass. You
   may **add** a `web` job to `.github/workflows/ci.yml` (install, lint, typecheck, test, build).
   Do not edit the existing steps.
4. **No secrets, no tracking, no real personal data.** No API keys in the code. No analytics.
   Only the demo users from the mocks.
5. **Assets must be legal to ship:** your own models, CC0 or public-domain textures (e.g.
   NASA Blue Marble for the Earth), and open-licensed fonts. Credit them in `web/CREDITS.md`.
6. **Design skills** are installed in `.claude/skills/`: `frontend-design` (Anthropic),
   `design-taste-frontend` and `impeccable`. Use them. **`impeccable` is installed docs-only:
   never run, download or install its `scripts/impeccable` CLI or any binary.** Skip the steps
   that need it (context loading, live mode, pinning) and apply its reference guides by reading
   them.
7. **Honest product copy:** everything is "indicative eligibility, not a loan offer or
   approval". Every number in the pitch must come from `README.md` or the mocks (they were
   measured), never invented.

---

## 1. The product

A ClickPe product (ClickPe: a Y Combinator-backed fintech from **Surat**) that tells
borrowers which personal loans they **really** qualify for, and why, *before* they apply,
so a rejection never dents their credit score. Pick a product name: propose 2–3 options in
the PR, and use a working name such as **"ClickPe Match"** until the owner decides.

### What the backend really does (use it in the story)
- **Crawls** lender websites daily (40 pages: bank sites, BankBazaar, Paisabazaar) while
  respecting robots.txt, and **never bypasses** bot protection.
- **AI reads each page once** (Amazon Nova Pro) and must **quote evidence** for every
  number. Code verifies the quote, and anything unverifiable never rejects anyone.
- **The Treasure Hunt:** 10,000 users × 59 products = **590,000** pairs →
  **164 equivalence classes** → **5 AI calls (~$0.02)** → a brute-force proof finds **0
  mismatches**, in 40 s. Later runs make 0 AI calls.
- **Live and automatic:** when a lender changes its criteria, every user is re-matched
  (product mode: 110,066 pairs → 18 classes → 1 AI call, 36 s) and notified.
- Upload → match → personalized email in **seconds** (event-driven: S3 → SQS → Lambda →
  webhook → n8n).

---

## 2. Site map (one site)

| Route | Who | What |
|---|---|---|
| `/` | everyone | The scroll-story landing page (§3) |
| `/check` | a borrower | "Check my eligibility": income, credit score, age, employment type → their dashboard |
| `/dashboard` | a borrower | Their matches and tools (§4). Opened by `/check` or by the signed link in the email |
| `/ops` | operator / reviewer | Upload a CSV, watch the pipeline and the Treasure Hunt funnel (§5) |

Mobile-first and responsive. Respect `prefers-reduced-motion`: it gets a static, still
beautiful version of the landing page.

---

## 3. Landing: a scroll story (the pitch)

Cinematic and premium (think Apple product pages, Stripe, Linear), but warm and Indian.
Scroll drives the scene. The owner's story, in order (refine the beats freely):

1. **Earth.** A 3D globe slowly rotating in space. Scrolling zooms across India and lands
   on **Surat** with a glowing pin.
2. **The problem.** Ordinary people in Surat (stylized 3D figures: a shop owner, a young
   salaried professional, a self-employed designer) each hit the wall: confusing criteria
   on 10 different sites, a rejection, a credit score that drops. Short, human captions.
3. **The team arrives.** Stylized 3D engineer and founder figures walk in and "present" the
   product to the viewer. **Two of them carry a light, caricature-style resemblance to
   ClickPe's cofounders** (hairstyle, glasses, attire, built from public photos the owner
   provides). Keep it clearly stylized and respectful, not photoreal.
4. **How a normal person uses it.** One persona's journey, animated: enter 4 numbers →
   matches appear ranked → "why you qualify" → shortlist the top 3 → compare → email arrives.
5. **Under the hood (the engineering pitch).** The pipeline as an animated diagram (crawler →
   AI with evidence → Treasure Hunt funnel → matches → email). The 590,000 → 164 → 5 funnel
   should be the visual climax: pairs collapsing into classes, with the "0 mismatches" proof.
6. **Trust.** Respects robots.txt, verified quotes, never emails real CSV addresses, and
   "indicative eligibility, not an offer".
7. **CTA.** "Check my eligibility" → `/check`, and "See the engine" → `/ops`.

Suggested stack (change it if you have a better reason): **Vite + React + TypeScript**,
**react-three-fiber + drei** for 3D, **GSAP ScrollTrigger** or **Lenis** for scroll,
**Tailwind** for styling. Performance budget: interactive on a mid-range phone, lazy-load the
3D, compress models (glTF + Draco/Meshopt), and avoid a huge first load.

---

## 4. Borrower dashboard: the features

Ordered by impact. The first four use data that no other comparison site has. Make them shine.

1. **"Unlock more" simulator.** Sliders for income and credit score (and age): the list
   re-ranks live and "+4 lenders unlocked" animates in. Advice line: "Raise your score by 30
   to unlock HDFC and ICICI." Compute it client-side from `products.json` hard criteria
   (`min_monthly_income`, `min_credit_score`, `min_age`/`max_age`, `employment_types`), and
   label it an estimate: the server also applies compiled free-text rules.
2. **Best platform per lender.** Products are *lender × channel* (`direct`, `bankbazaar`,
   `paisabazaar`). Group by `lender_key` and show "ICICI: 10.6% direct vs 10.9% on BankBazaar".
3. **Explainable fit score.** `fit_score` (0–100) with a breakdown: tier (eligible 60 /
   may-qualify 35), income headroom (`fit_reasons.income_multiple`), credit margin
   (`fit_reasons.credit_margin`), and rate (`fit_reasons.rate_from`). The formula is in
   `sql/matching/stage3_expand.sql`. `requirements` = "you'll also need…".
4. **Watch alerts.** A toggle for "notify me when a new lender matches or a rate drops". It's
   real: the daily crawl re-matches users automatically.
5. **Wishlist → pick top 3 → side-by-side compare:** rate range, EMI, total interest, max
   amount, tenure, requirements, verification badge.
6. **EMI and total-cost calculator** per offer (amount and tenure sliders), and the cost
   difference across the top 3.
7. **Document checklist** for the shortlist: merged, de-duplicated `requirements` and
   `other_criteria_text`.
8. **Trust badges:** `verification` (`ok` = verified quote; otherwise "may qualify"), "checked
   from source on `last_seen_at`", and a link to `product_url`.
9. Hide / not interested; an application status tracker (applied / approved / rejected).

Tiers: `eligible` = meets every published rule; `conditional` = may qualify (some criteria
can't be checked from 4 numbers). Never call anything "approved".

---

## 5. Ops console (`/ops`): the engine, visible

- **Upload a CSV.** Re-implement `loan_engine/api/ui.html` beautifully: presigned POST to S3,
  then poll `GET /uploads/{job_id}`. Show the live stages: received → loaded (+ rejects) →
  matching → emails.
- **Treasure Hunt funnel** for the latest run, from `pipeline_runs.json`: naive pairs →
  pairs after SQL → classes → class × product → AI calls → matches, plus `correctness_ok`,
  duration and cost. Include a history table of runs (upload vs product mode).
- **Crawl health** by channel and status (`crawl_health.json`).
- **Recent workflow errors** (`workflow_errors.json`): Workflow E records them.

---

## 6. API contract (the backend session implements this; you build against the mocks)

Base URL from `VITE_API_BASE`. **When it is unset, read `/mock/*.json` instead** (mock mode),
so the site always works for a demo. Responses are JSON. Money is in rupees per month,
rates in % p.a., dates in ISO 8601.

| Method & path | Request | Response (shape) | Mock |
|---|---|---|---|
| `POST /check` | `{monthly_income, credit_score, employment_status: "salaried"\|"self_employed"\|"business", age, name?}` | `{token, user_id, job_id}` (matching runs async) | pick a mock user |
| `GET /me` | `Authorization: Bearer <token>` | `{user, matching: "running"\|"done", summary: {matches, eligible, lenders, best_rate}}` | `users.json` |
| `GET /me/matches` | bearer | `[match + product fields]` (join `matches.json` × `products.json` on `product_id`) | both files |
| `GET /me/shortlist` / `PUT /me/shortlist` | bearer; `{product_ids: [], top3: []}` | same shape | localStorage in mock mode |
| `PUT /me/preferences` | bearer; `{hidden: [], alerts: true}` | same | localStorage |
| `GET /ops/runs` | none (aggregates only, no personal data) | `pipeline_runs.json` shape | yes |
| `GET /ops/crawl` | none | `crawl_health.json` shape | yes |
| `GET /ops/errors` | none | `workflow_errors.json` shape | yes |
| `POST /uploads`, `GET /uploads/{job_id}` | **exists today**: see `loan_engine/api/handler.py` | presigned POST / job status | fake a progress sequence |

The token is a short-lived signed token (HMAC of user_id + expiry) issued by `/check` or
embedded in the email's "view my matches" link (`/dashboard?t=<token>`). Store it in memory or
sessionStorage only.

Keep every API call in one typed module (`web/src/api/`), with types that mirror the mock JSON.

---

## 7. Definition of done

- `web/` builds with `npm ci && npm run build`; lint and typecheck are clean; unit tests cover
  the logic (simulator eligibility, EMI maths, best-platform grouping, the mock/live switch).
- Works in mock mode with no backend. Smooth on mobile, and reduced-motion is respected.
- `web/README.md`: how to run, the env vars, the design notes, the asset credits.
- Screenshots or a short screen recording of each section, attached to the PR.
- The PR description lists the proposed product names and anything that needs a backend
  change (the backend session will implement it).
