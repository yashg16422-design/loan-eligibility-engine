# ClickPar Match: landing page (`web/`)

The scroll story at `/` that pitches ClickPar Match and hands borrowers to the app at
`/app/` (built in [`dashboard/`](../dashboard/)). This folder is the landing only. The
check, dashboard and ops pages live in `dashboard/` (see `docs/EXTRAS_SPEC.md`, update of
2026-10-09).

> Indicative eligibility from published lender criteria. Not a loan offer or approval.

## The story, in scroll order

| # | Section | What happens |
|---|---|---|
| 1 | `#hero` | "Know your yes before you apply." over a slowly spinning dotted Earth; four measured numbers (590,000 / 164 / 5 / 0). |
| 2 | `#statement` | The problem, revealed letter by letter: rules learned by getting rejected, and the credit score cost. |
| 3 | `#globe-beat` | The globe locks on India (lit in the accent), then zooms into Surat and raises a pin that settles just above centre, with the caption pinned right under it. |
| 4 | `#ask` | "What's stopping your loan?": borrower questions type themselves in at random free spots (never over the heading, the ask box or each other), stay to be read, then fade. Each is tagged with the feature that answers it. Ask your own and get an answer card. |
| 5 | `#comic` | Two frames: engineers pitch the founders ("YES!"), then the team gathers round a laptop; the camera dives into the screen, which becomes the launch lockup. |
| 6 | `#journey` | Horizontal rail: Aarav (a real demo profile) checks his loans in five steps, with real matches, fit score and EMIs. |
| 7 | `#engine` | The pipeline draws itself: crawl → robots.txt → Nova Pro → 59 products → 590,000 pairs → 164 classes → 5 AI calls → 276,594 matches → 0-mismatch proof → email. |
| 8 | `#proof` | A live ticker of the 26 lenders, verified quotes, and the trust rules. |
| 9 | `#invite` | "Four numbers. Every lender. Your answer in seconds." Then the footer. |

Calls to action: **Check my eligibility → `/app/`**, **See the engine → `/app/ops`**.

## Run it

**Machine:** Mac laptop. **Directory:** `web/`

```zsh
npm ci
npm run dev          # http://localhost:5173 (the /app/ links need the api, see below)
npm run lint         # ESLint (typescript-eslint)
npm run typecheck    # tsc --noEmit, strict
npm test             # vitest: pure logic + every quoted number re-derived from the mocks
npm run build        # -> web/dist/ (static files)
npm run preview      # serve dist/ on http://localhost:4173
```

`VITE_APP_URL` sets where the app lives. The default is `/app/` (same origin). For a landing
hosted on a different origin, build with e.g. `VITE_APP_URL=https://<api-host>/app/ npm run build`.

## How it's built

- **Vite + TypeScript, no UI framework.** The page is static HTML (`index.html`) with
  scroll-driven scenes, so each section is a small module that enhances its own markup.
  React would only add a reconciler between GSAP and the DOM. The app in `dashboard/` stays
  React.
- **Pure logic is separate from DOM code**, and tested:
  - `src/lib/`: EMI, fit score, offer ranking, question routing, pipeline layout, comic camera
    and geo maths.
  - `src/landing/`: one module per scene.
- **Numbers can't drift.** `src/content/demo.ts` holds what the page quotes about the demo
  borrower. `content.test.ts` recomputes each value from `public/mock/*.json` (the live
  database export) and the pipeline figures from `README.md`. It also checks that every primary
  CTA points into the app.
- **Performance:**
  - three.js and the 220 KB of globe data load lazily, after the page is interactive (their own
    chunk).
  - The comic cast is its own chunk.
  - Fonts are self-hosted, so the page makes no third-party requests.
  - The globe stops rendering while it is off screen.
- **Reduced motion** (`prefers-reduced-motion`): no intro, no smooth scroll and no pinning.
  Every scene renders in its finished state as a still page.
- **Accessibility:**
  - Keyboard reachable throughout, with visible focus.
  - The section rail closes on Escape, and its tap targets are 44 px on phones.
  - Decorative motion is `aria-hidden`; the ask form is the accessible path.
  - The statement is read once via `aria-label`.
- **No tracking, no secrets.** `localStorage` holds only the chosen accent colour, and
  `sessionStorage` only whether the intro has played.

```
web/
  index.html              all markup; %APP_URL% is replaced at build time
  src/main.ts             boots the scenes in document order (ScrollTrigger measures in creation order)
  src/landing/*.ts        one module per scene: nav, intro, statement, ask, comic, journey, engine, proof, globe
  src/lib/*.ts            pure logic + logic.test.ts
  src/content/demo.ts     quoted numbers + content.test.ts (checked against the mocks)
  src/styles/landing.css  tokens, palettes, layout
  public/mock/            copy of docs/extras/mock/ (spec §0.2)
  public/geo/globe.json   Natural Earth dots (scripts/build_geo.py)
  scripts/                how the committed data files were generated (not run in CI)
```

## Design tokens

- True black page (`--bg #000`), hairline boxes, Inter plus JetBrains Mono for measurements.
- Colour carries meaning: **accent = yes/eligible**, coral = rejection, amber = lenders and
  their rules, violet = AI and engine.
- The accent is switchable from the section rail. **Glacier blue is the default** (the owner's
  pick). The options are glacier, mint, **marigold (the app's `#F2A93B` from
  `dashboard/DESIGN.md`)**, volt, rose and mono.
- The default is set by `--acc` in `src/styles/landing.css`, `DEFAULT_PALETTE` in
  `src/landing/nav.ts` and the inline script in `index.html`. Marigold sits close to the amber
  used for "lenders and rules".

## Integration notes (for merging with the app)

1. **Serving `/`.** The api Lambda serves `dashboard/` at `/app/` from `loan_engine/api/static/`.
   The landing builds to `web/dist/` and needs a `GET /` (plus `/assets/*`, `/geo/*`,
   `/favicon.svg`) route serving those files the same way. Alternatively, host `dist/` on any
   static host and build with `VITE_APP_URL` pointing at the api. This folder does not touch
   `loan_engine/` (spec §0.1), so the route is left to the backend session.
2. **Name.** The product is **ClickPar Match** (startup: ClickPar). `dashboard/` still says
   "ClickPe Match" (`index.html` title, `package.json` name) and should be renamed to match.
3. **CI.** A separate `web` job (lint, typecheck, test, build). Existing jobs are unchanged.
