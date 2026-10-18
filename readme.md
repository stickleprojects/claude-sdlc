# claude-sdlc

A working pipeline that implements Anthropic's [AI-native SDLC playbook](https://claude.com/resources/articles/the-ai-native-sdlc-playbook). This first version is deliberately simple. The aim is to make it general later: any language, and any AI tool.

The playbook replaces handoffs between teams with a loop. Each stage commits a file the next stage reads. Claude drafts, and people decide at the gates.

```
intent.md ─► spec.md ─► plan.md ─► code + tests ─► PR + AI review ─► release
   Plan       Design     Build        Test            Deploy
```

**Start here:** [docs/roles.md](docs/roles.md) explains, step by step, what each person does. Current status and paused work: [docs/progress.md](docs/progress.md).

## Quick start

```
make setup        # install dependencies
make check        # lint + tests + validate the artifact chain (exit 0 = healthy)
uv run sdlc new add-login       # start a change: changes/0001-add-login/intent.md
uv run sdlc status              # stage each change has reached
```

In Claude Code, the stages are skills: `/intent`, `/spec`, `/plan`. The `verifier` subagent checks finished work.

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

## GitHub setup

1. Run `claude setup-token` and save the token as the `CLAUDE_CODE_OAUTH_TOKEN` repository secret: `gh secret set CLAUDE_CODE_OAUTH_TOKEN`. The Claude review, mention, spec and eval workflows all use it. It is tied to a Claude subscription, so CI usage counts against that plan's limits. That's why agent evals run only on demand (Actions → Agent evals → Run workflow).
2. Install the Claude GitHub app (`/install-github-app` in Claude Code). `claude-code-action` needs it. Skip the installer's API key step, and don't merge the workflow PR it opens: this repo already has its own workflows.
3. Turn on branch protection for `main`: require a PR, the `CI / check` status, and a code owner's approval.

## Roadmap

- [ ] **Maintain stage:** a deterministic metric check against a baseline, with response tiers in `bands.yaml` (log, then read-only diagnosis, then a fix PR). Diagnoses are written as a new `intent.md`.
- [ ] Scheduled security scans whose findings become intents or fix PRs.
- [ ] Managed settings for guardrails engineers can't override.
- [ ] Switch CI authentication to identity federation with API billing: short-lived tokens, so evals can run on every config change and nightly again.
- [ ] More agent adapters in `scripts/agent.sh`, and a second sample stack to prove the stack contract.
- [ ] Terminal demo animations for each role: see [docs/demo-animation-plan.md](docs/demo-animation-plan.md).
