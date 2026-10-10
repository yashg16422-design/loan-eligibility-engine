# App design system (/app): one product with the landing page

**Mode:** Operate. The landing (`web/`, Persuade) tells the story; the app is where people
work. It uses the **landing's world exactly**, so moving from `/` to `/app/` feels like one
product: `web/src/styles/landing.css` is the source of these tokens.

## Tokens (gothic, on the landing's structure)

The app keeps the landing's structure (sharp hairline boxes, ticks, Inter + JetBrains Mono,
colour as meaning) in its own gothic palette, the owner's direction: violet-black night,
amethyst for every "yes", display serif for titles.

| Token | Value | Meaning |
|---|---|---|
| `bg` | `#07050A` | violet-black page |
| `panel` / `panel-2` | `#0E0A14` / `#16101F` | boxes, menus |
| `line` / `line-hi` | `#2A2236` / `#463A5C` | hairlines (structure, never decoration) |
| `fg` / `mute` / `dim` | `#EFE9F7` / `#A196B4` / `#5B5069` | text |
| `acc` (amethyst) | `#A07CFF` | yes, eligible, results, focus |
| `acc-deep` | `#4F22B0` | the filled primary button, selected segments, selection |
| `coral` (crimson) | `#E5536B` | rejection, not eligible, failures, delete |
| `amber` (antique gold) | `#D8B45F` | lenders and their rules, "may qualify" |
| `peri` (verdigris) | `#6FB8A7` | the AI and the engine (Workflow B) |

Colour is information: a colour is used only for what it means above.
**Type:** Cormorant Garamond 700 for `h1`/`h2` only (page and section titles); Inter Variable
for everything else; JetBrains Mono for numbers that are measurements and for small labels.
**Shape:** sharp, radius 0 everywhere. A box is a hairline border on `panel`, with an optional
28 px coloured tick on its top edge saying what it is. **Space:** 1480 px max width, gutters up
to 64 px, 28-32 px inside boxes, 96 px between sections: the app breathes like the landing.

## Motion
None for decoration. Things move only when real data changes: a bar grows when its number
arrives (`grow-x` / `grow-y`, 0.6 s ease-out), a workflow box turns glacier when that stage
finishes. No entrance animations, no loops, no spinners. Reduced motion: transitions off.

## Information architecture
- **Overview `/app/`** (assignment first): bulk CSV upload (also in the header on every page) →
  the live pipeline for that upload (Upload → Validate and load → Workflow B → Workflow C) →
  charts that form as the run reports numbers → analytics of the uploaded users → Workflows
  A, B, C, E with their triggers and real numbers → recent runs.
- **Check `/app/check`**: four numbers through the same pipeline.
- **My matches `/app/dashboard`**: summary, save prompt, **Top 5** → **Also eligible** →
  **May qualify** → **Not eligible (with the exact rule missed)** → **Quick tips**; What if and
  Compare alongside.
- **Account `/app/account`**: Cognito sign-up (email code) / sign-in; saved checks (remove one, or start fresh); daily picks.
- **Data reset**: destructive actions confirm in place (the button becomes a sentence naming what goes, with Delete / Cancel), crimson only; admins see *Reset uploaded data* on Overview.

## Components
Custom `Select` (listbox, keyboard: arrows, Enter, Escape, type-ahead) replaces native selects.
Charts are plain elements (`ui/charts.tsx`): numbers printed next to every bar, no background
tracks, log scale only for the funnel (590,000 to 5). Rows, not cards, for long lists.
