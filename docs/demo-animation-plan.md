# Plan: terminal demo animations

Status: **plan only, not built yet.**

## Goal

Short animations with CLI commands typed on screen, one per role from [roles.md](roles.md). A viewer should see their part of the loop in under a minute.

## Tooling: VHS

[VHS](https://github.com/charmbracelet/vhs) by Charm. You write a `.tape` script (`Type "make check"`, `Enter`, `Sleep 2s`) and it renders a GIF, MP4 or WebM.

Why VHS:

- The scripts are text, so they're versioned and reviewed like code, and can be re-rendered whenever the commands change.
- It renders headlessly, so CI can rebuild the animations and they stay in sync with the repo.
- It can type at a set speed, pause, hide setup commands, and set the theme, font and size.

Alternative: record by hand with asciinema and convert with `agg`. That's more natural, but not reproducible.

## Making Claude's output repeatable

A live model gives different output every run, which breaks reproducible renders. The plan:

1. Add a `demo/bin/claude` shim. It prints canned output for each scene from `demo/transcripts/<scene>.txt`, streamed line by line so it looks live.
2. Each tape uses `Hide` to put `demo/bin` on `PATH` before recording starts.
3. Real commands (`make check`, `uv run sdlc status`, `git`) run for real in a scratch copy of the repo, so their output is true.
4. Captions say "Claude output abridged" wherever the shim stands in.

To use real Claude output instead, set `DEMO_LIVE=1`. The shim is skipped and you accept that each render differs.

## Scenes

| # | Role | Shows | ~Length |
|---|---|---|---|
| 0 | Overview | `sdlc status` as one change moves intent → spec → plan, with a diagram card | 30s |
| 1 | Originator | `/intent …`, Claude's questions, the `intent.md` it writes, `gh pr create` | 45s |
| 2 | Product owner | Reviewing the spec PR with `gh pr view` and `gh pr diff`, then a resolved policy concern | 40s |
| 3 | Engineer | Plan mode → `/plan` → `claude --worktree` → `make check` → verifier verdict | 60s |
| 4 | Engineer (bug fix) | Commit a failing test, `SDLC_LOCK_TESTS=1`, a blocked test edit, the fix | 40s |
| 5 | Code owner | Claude review summary, an `@claude` fix pushed, approval | 40s |
| 6 | Release manager | Claude's attempt at `deploy-prod` blocked by the gate, then a human runs it with authorization | 30s |

## Layout

```
demo/
  bin/claude            # canned-output shim
  transcripts/*.txt     # Claude output for each scene
  tapes/*.tape          # one VHS script per scene, plus common.tape (theme, size, PATH setup)
  out/                  # rendered GIF/WebM (git-ignored; published by CI)
```

- New `make demo` target: renders every tape. `make demo SCENE=3` renders one.
- CI renders on changes to `demo/**` or `docs/roles.md` and attaches the GIFs as artifacts.
- Embed the GIFs in `docs/roles.md` under each role's heading.

## Build order

1. `common.tape` and scene 6 (release manager). It's the shortest scene and has no model output, so it's a good test of the toolchain.
2. The shim and scene 1, to prove the canned-output approach.
3. The remaining scenes, the `make demo` target and the CI job.

## Open questions

- Output format: GIF (works everywhere, large files) or WebM/MP4 (small, but some Markdown viewers won't play them)?
- Canned Claude output, or live output re-recorded on demand?
- Where the rendered files live: committed, CI artifacts, or a docs site?
