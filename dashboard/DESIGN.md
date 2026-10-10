# App design system (/app)

**Mode:** Operate. The landing (`web/`, Persuade) tells the story; the app is where people work.
**Reference:** the owner's studio reference: true black, white type, grey hairlines, light
display headlines, tracked mono for data labels, a white primary button, an "On this page" rail.
Taken from it: palette and type. Not taken: eyebrow labels and section numbers above headings.

## Tokens

| Token | Value | Meaning |
|---|---|---|
| `bg` / `panel` / `panel-2` | `#000000` / `#0A0A0A` / `#121212` | page, boxes, selected rows |
| `line` / `line-hi` | `#1D1D1D` / `#2F2F2F` | hairlines (structure, never decoration) |
| `fg` / `mute` / `dim` | `#F4F4F4` / `#8F8F8F` / `#555555` | text; `fg` is also the UI accent (primary button, focus, active tab) |
| `acc` (green) | `#3ECF8E` | eligible, yes, done, success |
| `amber` | `#F2B94B` | may qualify, lenders and their rules |
| `coral` (red) | `#F2716B` | not eligible, rejected, failed, delete |
| `peri` (violet) | `#A48BFA` | the engine and the AI (Workflow B) |
| `acc-2` (blue), `teal`, indigo `#8F9CF9` | | neutral distributions: who the customers are |

The interface is black and white; colour appears only where it carries data.
**Type:** Inter Variable. `h1`/`h2` weight 300, tracking -0.035em (the reference's "Built for
scale"); body 400; `h3` 300-500. JetBrains Mono for measurements and for small labels
(`.label`: 0.7rem, uppercase, 0.14em tracking) that name a value. **Shape:** radius 0; boxes are
hairlines; the 28 px coloured tick on a box's top edge names what it is (workflow cards).

## Motion
None for decoration. Bars grow when their number arrives (`grow-x` / `grow-y`); a pipeline box
turns done when its stage finishes. Reduced motion: transitions off.

## Information architecture
- **Merchant console `/app/merchant` (also `/app/`)**: a sign-in gate for uploads (every account
  sees only its own uploads, because reviewers share one database). Workspace (tabs: Bulk upload
  with the live pipeline, Single lookup) → Metrics (default) → Analytics (dataset menu: your
  uploads or the reference) → History & runs behind expand rows (your uploads with View /
  Delete, matching runs, workflows with retries and errors). "On this page" rail at xl widths.
- **Check `/app/check`**: four numbers; a line points merchants to the console.
- **My matches `/app/dashboard`**: summary, save prompt, Top 5 (open) → Also eligible (open) →
  May qualify, Not eligible (collapsed, counts visible) → Quick tips; What if and Compare.
- **Account `/app/account`**: Cognito sign-up / sign-in; saved checks; daily picks.

## Components
`Disclosure` (full-width expand row, + / -), `OnThisPage` (rail), `Select` (listbox, keyboard),
`ConfirmDelete` (asks once, in place). Charts (`ui/charts.tsx`) print every number next to its
bar; no background tracks; log scale only for the funnel. Tables never wrap cells; they scroll.
