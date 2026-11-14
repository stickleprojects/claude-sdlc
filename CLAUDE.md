# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This repo implements the AI-native SDLC playbook: changes flow intent.md → spec.md → plan.md → code → PR. See `readme.md` for the overview and `.sdlc/docs/roles.md` for who does what.

## Commands

```
make setup       # install deps (uv sync)
make check       # lint + test + validate; the one command that must exit 0 before a PR
                 # (a docs-only branch skips test; FULL=1 runs everything)
make fmt         # format; FILES="a.py b.py" limits it to those files
make test        # uv run pytest -q
uv run pytest tests/test_artifacts.py::test_next_slug_increments   # a single test
make new-change NAME=<kebab-name>   # start a change
make status      # stage each change has reached
make next REF=origin/main   # each change's next step and the skill that owns it
make clauses CHANGE=0002    # a spec as one JSON block per requirement (the clause check reads it)
make evals       # agent evals (calls the model; in CI it uses CLAUDE_CODE_OAUTH_TOKEN)
scripts/next-version.sh --explain   # the version the next release would get
```

A healthy `make check` ends with `ok: N change(s) valid`.

## What this repo is

Change tracking: issues

The framework itself. Its changes are tracked as GitHub issues (label `pipeline`), not `changes/` folders; .sdlc/REVIEW.md reads the line above. Product work happens in consumer repos (e.g. stickleprojects/sdlc-sandbox), which pull framework-owned files with `.sdlc/scripts/sync-sdlc.sh`. The list of framework-owned paths is in that script. Changing a framework-owned path, a `make` target name or an artifact's required sections affects every consumer: say so in the PR, and use a `!` title if it's a breaking change.

- Tests: `tests/test_hooks.py` and `tests/test_scripts.py` are unit tests for the hooks and scripts. `tests/test_scenario.py` installs the framework into a throwaway consumer repo (`tests/fixtures/consumer/`) and runs a change through it. When you change a hook, script, skill or the sync manifest, add a case there.
- PR titles follow conventional commits (`feat:`, `fix:`, `ci:`, …, `!` for breaking changes). They drive the version and the release notes.

## Architecture

- **Layout (#133):** everything synced to consumers lives in `.sdlc/`, and `scripts/` holds only the framework's own scripts (release, `docs-only.sh` for `make check`) plus a shim for older syncs. Claude Code and GitHub need a few files in their own folders:
  - a stub per skill in `.claude/skills/sdlc-<name>/SKILL.md` (the frontmatter and one line that runs `.sdlc/scripts/resolve.sh`) and for the verifier in `.claude/agents/sdlc-verifier.md`. A skill's body lives in `.sdlc/skills/<name>/SKILL.md`, so edit the body there and the name or description in the stub;
  - `.claude/settings.json`, whose hooks all call `.sdlc/hooks/dispatch.sh <event>`. A new hook is a row in `.sdlc/hooks/hooks.tsv`, never a settings change;
  - the workflows.

  Framework make targets go in `.sdlc/sdlc.mk`, not in a consumer's Makefile. A consumer changes framework files through overrides in `.sdlc-local/` (`.sdlc/src/sdlc/resolve.py`, `.sdlc/docs/overrides.md`), so anything that reads a skill, template, prompt or `REVIEW.md` must read it through the resolver.
- **Stack contract:** hooks, CI and evals call only the `make` targets above, never `uv`, `ruff` or `pytest` directly. Language-specific details live only in `Makefile` and `.github/actions/setup-stack/`. Keep it that way.
- **Agent adapter:** CI and evals call AI only through `.sdlc/scripts/agent.sh`. Don't call `claude -p` from workflows directly. (`claude-code-action` in the review and mention workflows is the one exception.)
- **Artifact chain:** `changes/NNNN-name/{intent,spec,plan}.md`. The required `##` sections are defined in `.sdlc/src/sdlc/artifacts.py` (`CHAIN`) and must match `.sdlc/templates/`. A test enforces this. Change both together.
- **Optional build plan:** `changes/NNNN-name/build.md`, written by `/sdlc-build` for builds of more than one session. It sits outside `CHAIN`; `check_build` validates it when present (sections from `.sdlc/templates/build.md`, no approval with open questions). Small plans are built without one.
- **Skills:** six entry skills people remember (`sdlc-intent`, `sdlc-plan`, `sdlc-build`, `sdlc-pr`, `sdlc-next`, and `sdlc` for updating the pipeline itself) route by a change's state (`.sdlc/src/sdlc/routing.py`, `.sdlc/skills/routing.md`) to internal ones (`sdlc-spec`, `sdlc-po-review`, `sdlc-review-findings`, `sdlc-agent-identity`, `sdlc-security-policy`, all `user-invocable: false`). A new skill is one or the other; `tests/test_routing.py` enforces it. Policy skills (e.g. `sdlc-security-policy`) are advisory; rules that must always hold need a hook or CI check.
- **Scope rules:** `.sdlc/skills/scope.md` (silence is not permission, a rule's scope is a minimum, descopes need a person's approval, test at the criterion's level) is shared by the plan, build, spec and review skills, the verifier and `.sdlc/REVIEW.md`. Change it there, not in each one.

## Guardrails (hooks in .claude/settings.json)

- You can't edit `.sdlc/hooks/*`, `.claude/settings.json`, lockfiles or `.env*`. Propose those changes for a human instead.
- A bug fix's failing test locks once it's committed (`test(<slug>): …` on a change with `bug.md`): the files that commit touched can't be edited, while new tests elsewhere still can (`.sdlc/scripts/tests-locked.sh`). `SDLC_LOCK_TESTS=1` locks every test file. Fix the code, not the test.
- No code before the plan (`.sdlc/hooks/plan-gate.sh`): on a branch or worktree named after a change, code edits wait until `changes/<slug>/plan.md` is committed (a bug with `bug.md` and `spec.md` committed on `build/<slug>` is the exception, #148). On `main`, only `changes/`, `docs/` and top-level `*.md` can be edited: start a branch first. `SDLC_PLAN_GATE=0` turns it off. CI holds the same rule (`.sdlc/scripts/check-plan-first.sh` in the `pr-title` job), since shell writes don't go through the hook.
- `make deploy-prod`, `git push` to main and force pushes are blocked. Push a branch and open a PR.
- Merging and approving PRs (`gh pr merge`, `gh pr review --approve`, the merge and review APIs) are blocked: a human merges. When a PR is ready, say so and stop.
- Edited files are auto-formatted after each edit through `make fmt FILES=...`.

## Conventions

- One stage at a time. Don't write a spec while drafting an intent, or code before `plan.md` is committed. The one exception is a bug on the fast path (#148), where one PR carries the bug, its spec and the fix.
- When the same mistake happens twice, add the correction here.

## Known mistakes

- The working copy may live on NTFS, where `chmod +x` has no effect and git commits scripts as `100644`. On Linux runners a non-executable hook fails silently, which turns the guardrail off. For every new script, run `git update-index --chmod=+x <file>` and check it with `git ls-files -s`.
