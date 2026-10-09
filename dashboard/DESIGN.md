# Dashboard design system (borrower dashboard + ops console)

**Mode:** Operate. People come here to finish a task: see what they qualify for, compare,
shortlist, and understand why. Scannability beats expression. The landing page (built
separately) persuades; this surface works.

**References (owner's choice):** daqconsulting.com for the world (dark graphite,
hairline structure, a self-building pipeline diagram, monospace only for measurements),
and weevolveit.com for one strip of real proof. Techniques are borrowed, not their visuals.
See `docs/extras/REFERENCE_NOTES.md`.

## Tokens

| Token | Value | Role |
|---|---|---|
| `--ink` | `#101315` | page (graphite, cool) |
| `--panel` | `#161A1D` | rails, tables, inputs |
| `--raise` | `#1D2226` | hover / selected rows |
| `--line` | `rgb(233 236 238 / 0.08)` | hairlines (structure, never decoration) |
| `--text` | `#E9ECEE` | primary text (16:1 on ink) |
| `--muted` | `#9AA3A9` | secondary text (7.2:1 on ink) |
| `--marigold` | `#F2A93B` | the one accent: primary action, current selection, focus |
| `--leaf` | `#7CC4A0` | semantic only: "eligible" marker |

Marigold, not acid green or vermilion: it is the colour of Surat's garland markets and
reads as "go" without borrowing a fintech-green cliché. It is used ONLY for actions,
selection and focus; never for decoration or inactive states.

**Type:** Geist Variable for everything (one family, Operate). Geist Mono Variable ONLY for
numbers that are measurements: rates, rupees, scores, counts in tables. Scale 1.2:
12 / 14 / 16 / 19 / 23 / 28 / 33 px. Sentence case everywhere. No eyebrows, no all-caps.

**Shape:** radius 6px for controls and panels, 999px for the segmented control only.
**Depth:** none by default; a raised surface is a lighter fill, not a shadow. Dialog-like
overlays get one soft shadow (`0 24px 48px rgb(0 0 0 / .45)`).

## Layout

```
Dashboard (>= 1024px)
+----------------------------------------------------------------------------+
| ClickPe Match                                   Shortlist (3)   Engine     |
+----------------------------------------------------------------------------+
| You qualify outright for 9 offers from 6 lenders. 31 more are possible.    |  <- sentence, not a hero metric
| Rs 52,000 a month, score 760, salaried, 31                     Adjust      |
+---------------------------------------------+------------------------------+
| [All 40] [Eligible 9] [May qualify 31] [Saved] |  What if...             |
| sort: best fit v                              |  income  ----o----       |
|---------------------------------------------- |  score   ------o--       |
| Axis Bank            9.5% - 21.6%   up to 40L |  age     --o------       |
|   best on BankBazaar, also direct  [save]     |  +4 lenders at 790:      |
|   > why: income 3.5x the minimum ...          |   HDFC, ICICI ...        |
| ...                                           |----------------------    |
|                                               |  Compare (3)  [open]     |
+---------------------------------------------+------------------------------+
Mobile: single column; the what-if panel becomes a section after the list.
```

The list is one lender per row (the best platform for that lender), so the same bank
never appears three times; the other platforms open inline. Left-aligned throughout.

## Signature moments (boldness spent in exactly two places)

1. **Dashboard: the what-if simulator.** Moving a slider re-evaluates every product with
   the same rules as the SQL (hard criteria + compiled rules) and the rows that change
   tier animate in place (layout animation). This is the product's point of view.
2. **Ops: the pipeline builds itself** once, from the real latest run: users x products
   -> naive pairs -> classes -> AI calls -> matches -> emails, packets travelling between
   nodes (the DAQ technique). Reduced motion: drawn complete, no travel.

Everything else stays still. Motion on interaction only: 160-220 ms, ease-out.

## Self-review against generated-design defaults (and what changed)

- "Big number + small label" headline: replaced by one plain sentence with the numbers.
- Identical rounded cards for offers: replaced by a dense, aligned list (rows, not cards).
- Mono as a "technical" costume: mono restricted to measurements.
- Near-black + one neon accent: graphite + marigold, with the accent rationed to actions.
- Glass/blur: not used. DAQ's glassy cards were decoration; here a fill change does it.
- Numbered markers: only in the ops pipeline, where the order is the content.

## Quality floor
Keyboard reachable, visible focus ring (marigold, 2px offset), `prefers-reduced-motion`,
contrast >= 4.5:1 for text, themed selection and scrollbars, tabular numerals, skeleton
loading, empty and error states written as directions.
