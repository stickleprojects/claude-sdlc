# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This repo implements the AI-native SDLC playbook: changes flow intent.md → spec.md → plan.md → code → PR. See `readme.md` for the overview and `docs/roles.md` for who does what.

## Commands

```
make setup       # install deps (uv sync)
make check       # lint + test + validate; the one command that must exit 0 before a PR
make fmt         # format; FILES="a.py b.py" limits it to those files
make test        # uv run pytest -q
uv run pytest tests/test_artifacts.py::test_next_slug_increments   # a single test
make new-change NAME=<kebab-name>   # start a change
make status      # stage each change has reached
make evals       # agent evals (calls the model; in CI it uses CLAUDE_CODE_OAUTH_TOKEN)
scripts/next-version.sh --explain   # the version the next release would get
```

A healthy `make check` ends with `ok: N change(s) valid`.

## What this repo is

The framework itself. Product work happens in consumer repos (e.g. stickleprojects/sdlc-sandbox), which pull framework-owned files with `scripts/sync-sdlc.sh`. The list of framework-owned paths is in that script. Changing a framework-owned path, a `make` target name or an artifact's required sections affects every consumer: say so in the PR, and use a `!` title if it's a breaking change.

- Tests: `tests/test_hooks.py` and `tests/test_scripts.py` are unit tests for the hooks and scripts. `tests/test_scenario.py` installs the framework into a throwaway consumer repo (`tests/fixtures/consumer/`) and runs a change through it. When you change a hook, script, skill or the sync manifest, add a case there.
- PR titles follow conventional commits (`feat:`, `fix:`, `ci:`, …, `!` for breaking changes). They drive the version and the release notes.

## Architecture

- **Stack contract:** hooks, CI and evals call only the `make` targets above, never `uv`, `ruff` or `pytest` directly. Language-specific details live only in `Makefile` and `.github/actions/setup-stack/`. Keep it that way.
- **Agent adapter:** CI and evals call AI only through `scripts/agent.sh`. Don't call `claude -p` from workflows directly. (`claude-code-action` in the review and mention workflows is the one exception.)
- **Artifact chain:** `changes/NNNN-name/{intent,spec,plan}.md`. The required `##` sections are defined in `src/sdlc/artifacts.py` (`CHAIN`) and must match `templates/`. A test enforces this. Change both together.
- **Stage skills:** `.claude/skills/{intent,spec,plan}`. Policy skills (e.g. `security-policy`) are advisory; rules that must always hold need a hook or CI check.

## Guardrails (hooks in .claude/settings.json)

- You can't edit `.claude/hooks/*`, `.claude/settings.json`, lockfiles or `.env*`. Propose those changes for a human instead.
- With `SDLC_LOCK_TESTS=1`, files under `tests/` are locked. Fix the code, not the test.
- `make deploy-prod`, `git push` to main and force pushes are blocked. Push a branch and open a PR.
- Edited files are auto-formatted after each edit through `make fmt FILES=...`.

## Conventions

- One stage at a time. Don't write a spec while drafting an intent, or code before `plan.md` is committed.
- When the same mistake happens twice, add the correction here.

## Known mistakes

- The working copy may live on NTFS, where `chmod +x` has no effect and git commits scripts as `100644`. On Linux runners a non-executable hook fails silently, which turns the guardrail off. For every new script, run `git update-index --chmod=+x <file>` and check it with `git ls-files -s`.
