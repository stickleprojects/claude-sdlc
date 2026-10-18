# claude-sdlc

A working pipeline that implements Anthropic's [AI-native SDLC playbook](https://claude.com/resources/articles/the-ai-native-sdlc-playbook). This first version is deliberately simple. The aim is to make it general later: any language, and any AI tool.

The playbook replaces handoffs between teams with a loop. Each stage commits a file the next stage reads. Claude drafts, and people decide at the gates.

```
intent.md ─► spec.md ─► plan.md ─► code + tests ─► PR + AI review ─► release
   Plan       Design     Build        Test            Deploy
```

**Start here:** [docs/roles.md](docs/roles.md) explains, step by step, what each person does.

## Getting started

### Prerequisites

- `git`, `gh` (logged in: `gh auth login`), `make`, `jq`, `uv`
- Claude Code (`claude`) with a Claude **Pro or Max** subscription. CI uses your subscription through a token, so there's no separate API billing.
- Owner or admin rights on the GitHub repo. Branch protection on a *private* repo needs GitHub Pro.

### 1. Get the code and check it builds

```
gh repo create <you>/<name> --private --clone   # or fork / copy this repo
cd <name>                                       # copy this repo's files in, then commit
make setup && make check                        # must end with "ok: N change(s) valid"
```

### 2. Configure GitHub: one script

```
scripts/bootstrap-github.sh --dry-run   # show what it would change
scripts/bootstrap-github.sh             # apply; safe to re-run
```

The script checks and fixes each item below. Every one of these broke the first time this repo was set up:

| # | Setting | Why it's needed | What goes wrong without it |
|---|---|---|---|
| 1 | Scripts committed as executable (`100755`) | NTFS and Windows checkouts lose the executable bit | Workflows fail with *Permission denied*, and **Claude Code hooks silently don't run** |
| 2 | `pipeline` label | Pipeline problems are tracked apart from product work | — |
| 3 | `.github/CODEOWNERS` names the repo owner | Branch protection requires a code owner's review | No one counts as owner, so the review rule has no effect |
| 4 | `CLAUDE_CODE_OAUTH_TOKEN` secret | Every Claude workflow logs in with it | The review fails instantly with no model usage. The script tests the token before saving it, and copes with line-wrapped pastes. |
| 5 | Actions may create PRs | *Spec from intent* opens the spec PR | *"GitHub Actions is not permitted to create or approve pull requests"* |
| 6 | Branch protection on `main` | Requires a PR, the `check` status and a code owner's approval; admins can bypass | Anyone, including the agent, could push straight to `main` |

It **can't** do these two; they need you:

| # | Step | How |
|---|---|---|
| 7 | Install the **Claude GitHub app** | https://github.com/apps/claude → *Configure* → *Only select repositories* → add the repo. Without it the review fails with *"Claude Code is not installed on this repository"*. `/install-github-app` does the same, but skip its API-key step and don't merge the workflow PR it opens. |
| 8 | **Trust the workspace** in Claude Code | Run `claude` in the repo once and accept the prompt. Until then, the allow rules in `.claude/settings.json` are ignored. |

If the script changed any files (items 1 and 3), commit them in a PR.

### 3. Check it works

Open any small PR. Both **check** and **review** should pass, and Claude should post a single *Review summary* comment. Expect two quirks:

- **A PR that changes `.github/workflows/claude-*.yml` gets no AI review.** The action skips itself on purpose until the file matches `main`, so review those PRs by hand.
- **On a solo repo you can't approve your own PRs.** Merge with *"merge without waiting for requirements"*, or run `gh pr merge <N> --merge --admin`.

### 4. Daily use

```
uv run sdlc new add-login       # start a change: changes/0001-add-login/intent.md
uv run sdlc status              # stage each change has reached
make check                      # lint + tests + artifact chain
```

In Claude Code, the stages are skills: `/intent`, `/spec`, `/plan`, plus `/po-review <PR#>` for product owners. The `verifier` subagent checks finished work. Who does what: [docs/roles.md](docs/roles.md).

## How it is put together

| Stage | Artifact | Automation |
|---|---|---|
| Plan | `changes/NNNN-*/intent.md` | `/intent` skill |
| Design | `spec.md` | `/spec` skill; the *Spec from intent* workflow opens a spec PR when an intent merges |
| Build | `plan.md` + code | plan mode, `/plan`, worktrees, hooks (format on edit, protected paths) |
| Test | tests, evals | `make check`; *Agent evals* (on demand for now) |
| Deploy | PR | *Claude review* follows [REVIEW.md](REVIEW.md); `@claude` fixes; production gate hook |

### Two abstraction seams

These keep the project general:

- **Stack contract:** hooks, CI and evals call only `make setup | fmt | lint | test | validate | check`. The current stack is Python with uv. To switch language, change the [Makefile](Makefile) and [.github/actions/setup-stack](.github/actions/setup-stack/action.yml).
- **Agent adapter:** every non-interactive AI call goes through [scripts/agent.sh](scripts/agent.sh). Add another agent there; `AGENT=echo` does a dry run without calling a model.

The `sdlc` CLI (in `src/sdlc/`) is the pipeline's own tooling. It also gives the pipeline real code to build and test.

CI usage counts against your Claude plan's limits. That's why agent evals run only on demand (Actions → Agent evals → Run workflow). Known pipeline gaps are tracked as [`pipeline` issues](../../issues?q=label%3Apipeline).

## Roadmap

- [ ] **Maintain stage:** a deterministic metric check against a baseline, with response tiers in `bands.yaml` (log, then read-only diagnosis, then a fix PR). Diagnoses are written as a new `intent.md`.
- [ ] Scheduled security scans whose findings become intents or fix PRs.
- [ ] Managed settings for guardrails engineers can't override.
- [ ] Switch CI authentication to identity federation with API billing: short-lived tokens, so evals can run on every config change and nightly again.
- [ ] More agent adapters in `scripts/agent.sh`, and a second sample stack to prove the stack contract.
- [ ] Terminal demo animations for each role: see [docs/demo-animation-plan.md](docs/demo-animation-plan.md).
