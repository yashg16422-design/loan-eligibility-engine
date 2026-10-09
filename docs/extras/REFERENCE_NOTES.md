# Reference notes: scroll, content boxes and flow of two sites the owner likes

**Observation only, no copying.** These notes describe *techniques and pacing* from
weevolveit.com and daqconsulting.com so the UI agent can reach a similar level of craft.
Do not copy their text, logos, images, colours or layouts one to one. You keep full creative
freedom, and your own notes and judgement take priority over anything here.

**How these were gathered:** the reviewing browser blocked both sites' scripts, styles and
images, so the motion was not watched live. Everything below is **inferred from the rendered
DOM**: element heights, sticky containers, transform tracks, `data-*` attributes and class
names. Treat the timings as educated guesses and the structure as reliable.

---

## daqconsulting.com: a cinematic, pinned-scene narrative (dark, technical)

Stack: Next.js + Tailwind, **Lenis smooth scroll** (`lenis lenis-smooth` on `<html>`), one
`<canvas>` (WebGL-style hero), and SVG for the diagrams. The page is about 10,000 px tall but
has only **5 scenes**: few sections, each one long and pinned.

1. **Intro curtain, once per session.** An inline script sets `data-intro="play"` only if
   `sessionStorage` has no flag **and** the user doesn't prefer reduced motion. A returning
   visitor (same session) or a reduced-motion user goes straight to the page. This is a good
   pattern for our Earth → Surat intro: play it once, never trap the user.
2. **Full-viewport hero** (`100svh`, `overflow-hidden`) over the canvas: one very short
   headline, one line of supporting text, and an SVG element marked `data-travel` (something
   moves along a path). A fixed, centred, floating header with `pointer-events-none` on the bar
   and clickable items inside.
3. **Pinned statement reveal:** a `250vh` section with a `sticky top-0 h-[100svh]` child
   holding **one statement split into about 55 per-character spans**. Scroll drives the
   letters (opacity or colour fill) while the frame stays pinned. It's one idea, given room to
   breathe.
4. **Pinned pipeline diagram (the centrepiece):** a `230svh` section with a sticky `100svh`
   stage containing an **SVG architecture diagram that builds itself as you scroll**:
   - nodes in order *source → bronze → silver → gold → serve* (the data plane), plus two
     *control-plane* nodes drawn apart from the main row
   - each node has `node-frame` (rect), `node-title` (text) and `node-icon` (group), revealed
     one after another (`data-build`, `data-motion`)
   - `data-strand` / `data-signal` / `data-packet` / `data-arrival`: connecting lines draw in,
     **packets travel along them**, and the target node pulses on arrival
   - about 8 short text blocks (~80 characters each) beside the diagram, synced to the active
     node
   - **Why it matters to us:** this is exactly our story. *Crawl → AI with evidence → compile
     rules → equivalence classes → matches → email*, with the 590,000 → 164 → 5 funnel as
     the packets collapsing.
5. **Pinned card "sheets":** a tall (~3,900 px) section with a sticky, overflow-clipped stage
   and **5 linked cards** (`shrink-0`, so a horizontal or stacked track) with a CSS variable
   `--ink` that scroll animates (cards "ink in" from faint to full). Cards are glassy
   (`bg-white/[0.02]`, `border-white/…`, hover brightens the border over 700 ms) and short
   (15–28 words each).
6. **Footer as an invitation:** a full-screen closing statement plus one CTA, with decorative
   SVG. It reads like the last slide of a pitch, not a link dump.
7. **Details:** an opt-in **sound toggle** (off by default), Inter for text plus a **monospace
   accent** for technical labels, hairline borders (`white/5`), `svh` units for mobile
   browser bars.

## weevolveit.com: a rich, multi-proof page with a horizontal method rail

Stack: Next.js + Tailwind, one `<canvas>`, a custom cursor, about 16,000 px tall.

1. **Hero = a pinned visual layer + content scrolling over it.** A `100svh` background layer
   (the canvas) stays behind while a long content column (about 6,400 px) scrolls over it on
   **glass panels** (`backdrop-blur-xl`). The hero headline is followed by a **stats strip**
   (years · projects · countries · rating) and an **image carousel** (14 items).
2. **Proof walls inside the flow:** a large logo wall (dozens of client logos) and **16 review
   quotes** (`data-review-quote`), clamped with "read more" (`data-clamped`). Proof comes early
   and is dense.
3. **A 5-step method as a pinned horizontal rail:** `data-method` → a `rail` (`h-screen
   w-screen overflow-hidden`) containing a `track` (`w-[350vw]`, `will-change-transform`)
   that **translates sideways while you scroll down**. 5 slides, each with a **huge watermark
   numeral (01–05)**, a step name, a tagline and 3 bullets. The section **flips the colour
   theme** (light section inside a dark page) through CSS variables (`--method-bg/fg/border`).
   **For us:** "how a normal person uses it" as 5 steps (enter 4 numbers → matches ranked →
   why you qualify → shortlist top 3 → email arrives).
4. **Interactive problem prompt:** a "what's slowing you down?"-style section, revealed
   with a **clip-path curtain** (`clip-path: inset(-100vh 0 0 0)`), where the visitor picks
   their pain point. **For us:** "What stops you from getting a loan?" → each choice leads into
   the feature that solves it.
5. **Micro-interactions:** a custom cursor that reacts to hoverable items
   (`data-cursor-hover`, 17 targets), **"candle glow" cards** (a soft glow following the
   pointer on service cards), and `tabular-nums` for animated counters.

---

## Patterns worth borrowing (translated to our product)

| Pattern | Seen on | Our use |
|---|---|---|
| Play-once intro, skipped on reduced motion | DAQ | Earth → India → Surat pin, once per session |
| Smooth scroll (Lenis) + sticky `100svh` stages inside 200–250vh sections | DAQ | Every story beat is a pinned scene, not a stack of boxes |
| Per-character statement reveal | DAQ | The problem line: rejections, confusing criteria, credit damage |
| Self-building SVG pipeline with travelling packets | DAQ | Crawler → AI evidence → Treasure Hunt funnel → matches → email (real numbers) |
| Horizontal pinned rail with giant step numerals and a theme flip | WeEvolveIT | The 5-step borrower journey |
| Stats strip right under the hero | WeEvolveIT | 590,000 pairs → 164 classes → 5 AI calls → 0 mismatches |
| Content scrolling over a fixed canvas on glass panels | WeEvolveIT | Earth or particles behind the early beats |
| Proof wall | WeEvolveIT | Sources crawled (lender names as text badges, not logos) + verified-quote examples |
| Interactive pain-point picker with a clip-path curtain | WeEvolveIT | "What stops you?" → jump to the matching feature |
| Cards that "ink in" on scroll; hover-brightened glass borders | DAQ | Feature cards, the team/founder cards |
| Footer as a full-screen invitation | DAQ | "Check my eligibility" as the final scene |
| Monospace accents for technical labels; tabular numbers | both | Pipeline labels, counters, the funnel |

## Pacing takeaways
- **Few scenes, each long.** DAQ tells everything in 5 pinned scenes. Fewer, deeper beats
  feel premium; many short sections feel templated.
- **One idea per screen.** Short headlines (3–4 words) and 1–2 lines of support. The
  diagram carries the detail.
- **Proof early, CTA last and big.**
- **Accessibility is built in:** reduced motion skips the intro, `svh` handles mobile bars,
  and sound is opt-in.
