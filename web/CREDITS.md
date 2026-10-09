# Credits

Every asset the landing page ships is either our own or carries a licence that allows shipping it.

| What | Where it's used | Source | Licence |
|---|---|---|---|
| Map data (land, India point-of-view borders, populated places) | Dotted globe (`public/geo/globe.json`, built by `scripts/build_geo.py`) | [Natural Earth](https://www.naturalearthdata.com/) | Public domain |
| Open Peeps illustrations by Pablo Stanley | Comic characters (`src/landing/cast.json`) | [openpeeps.com](https://www.openpeeps.com/) | CC0 1.0 |
| DiceBear (used only to render the Open Peeps SVGs, in `scripts/build_cast.mjs`) | Not shipped | [dicebear.com](https://www.dicebear.com/) | MIT |
| Inter (variable), by Rasmus Andersson | Body and headings, self-hosted via `@fontsource-variable/inter` | [rsms.me/inter](https://rsms.me/inter/) | SIL OFL 1.1 |
| JetBrains Mono | Labels and measurements, self-hosted via `@fontsource/jetbrains-mono` | [jetbrains.com/lp/mono](https://www.jetbrains.com/lp/mono/) | SIL OFL 1.1 |
| three.js | Globe rendering | [threejs.org](https://threejs.org/) | MIT |
| GSAP + ScrollTrigger | Scroll-driven timelines | [gsap.com](https://gsap.com/) | GSAP Standard License (free, including commercial use) |
| Lenis | Smooth scrolling | [lenis.darkroom.engineering](https://lenis.darkroom.engineering/) | MIT |

The logo mark, the pipeline diagram, the whiteboard, notes, laptop and all copy are our own.
Every figure in the page comes from `README.md` (measured on the live engine) or from the mock
export in `public/mock/`, and `src/content/content.test.ts` checks them against those sources.
