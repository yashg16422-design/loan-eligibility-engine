# Design skills (vendored, reviewed)

Copied on 2026-10-09 after a full read of every instruction file. Upstream licenses are kept
next to each skill.

| Skill | Upstream | Copied | License |
|---|---|---|---|
| `frontend-design` | [anthropics/skills](https://github.com/anthropics/skills) `skills/frontend-design/` | `SKILL.md` | see `LICENSE.txt` |
| `design-taste-frontend` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) `skills/taste-skill/` | `SKILL.md` | MIT |
| `impeccable` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) `.claude/skills/impeccable/` | `SKILL.md` + `reference/*.md` only | Apache-2.0 (+ `NOTICE.md`) |

**`impeccable` is docs-only on purpose.** Upstream, its first step runs `scripts/impeccable`,
a launcher that downloads and executes a prebuilt binary on first use. We do not ship or run
third-party executables in this repo, so the `scripts/` folder was left out. Agents should
skip the steps that need the CLI (context loading, live mode, pinning) and read the reference
guides directly.
