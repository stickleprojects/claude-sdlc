# Claude's own GitHub identity

By default, Claude sessions use your `gh` login and your git credentials, so their commits, PRs and review replies appear under your name. This page sets up a separate identity, a GitHub App, so they appear as `<app>[bot]` instead. GitHub can then also require *your* approval before anything Claude wrote can merge.

## Who acts as whom

[`.claude/personas.conf`](../.claude/personas.conf) lists every Claude persona and the identity it acts as:

| Persona | Identity | Where |
|---|---|---|
| `intent`, `spec`, `plan`, `build`, `dev`, `po-review` | `agent`: your App, `<app>[bot]` | local sessions |
| `spec-ci` | `agent` | the *Spec from intent* workflow |
| `reviewer`, `mention` | `claude`: Anthropic's Claude App, `claude[bot]` | the review and `@claude` workflows |

All the local personas share one App. Each comment is signed `— Claude (<persona>)`, and each commit carries an `Agent-Persona:` trailer, so you can still tell them apart. The reviewer is a different identity from the author, so Claude never reviews as the account that wrote the code.

To give a persona its own App later, add an `identity` line in `personas.conf`, point the persona at it, and run `setup --identity <name>`, or re-run `create --per-persona`.

## Set it up (once, about 5 minutes)

For a step-by-step walkthrough with every prompt and page you'll see, read [setup-agent-apps.md](setup-agent-apps.md).

1. **Create the App or Apps.** Run this from any repo that has the pipeline:
   ```
   scripts/agent-identity.sh create
   ```
   It asks before anything opens:
   - **one App for everything** (recommended), or **Apps per persona**;
   - with Apps per persona: **which personas get an App of their own** (e.g. plan, build, dev), then **which of those Apps each other persona shares** (e.g. intent, spec and po-review share plan's);
   - then it lists the Apps it will create, who each serves, and which can change workflows, and asks **Continue?**

   Without a terminal, or to script it: `--per-persona` (one App each), or `--groups "plan+intent+spec+po-review,build,dev"` (each group shares the App named after its first persona), and `--yes` to skip the confirmation.

   Then your browser opens on GitHub's *Create GitHub App* page with everything filled in: the name (`<owner>-claude`, or `<owner>-claude-<persona>`), permissions, no webhook, private. For each App:
   - click **Create GitHub App**;
   - on the install page, choose *Only select repositories*, pick the repos and click **Install**. GitHub then sends you back for the next App.

   It stores each App's private key in your keyring (Seahorse: *claude-sdlc GitHub App private key (<identity>)*) and its id and name in `~/.config/sdlc/<identity>.env`. With more than one App it also writes `~/.config/sdlc/personas.conf`, which maps each persona to its App and overrides the repo's copy. Choosing one App on a later run moves that file aside.

   Options: `--name <app name>` if the default is taken (App names are unique across GitHub, 34 characters at most); `--org <org>` to create the Apps under an organization; `--no-browser` to print the URL instead.

   **Permissions:** contents, pull requests and issues read and write; actions, checks, commit statuses and metadata read. Workflows write goes to the App that serves `build` and `dev`, so in per-persona mode only those two can change `.github/workflows/`.
2. **Configure each repo:** `scripts/bootstrap-github.sh --mode team --skip-token`. Step 8 checks each App is installed on the repo, and gives the workflows the App that `spec-ci` uses (the `SDLC_AGENT_APP_ID`/`_SLUG` variables and the `SDLC_AGENT_APP_KEY` secret). Team mode makes GitHub require a code owner's (your) approval on every PR.
3. **Check:** `scripts/agent-identity.sh check` should print `ok: a token for this repo was issued`.

**Adding a repo later:** install the App(s) on it from the App's page (*Install App* → *Configure*), then run step 2 there.

**By hand instead:** create the App under *Settings → Developer settings → GitHub Apps* with the permissions above, generate a private key, install it, and run `scripts/agent-identity.sh setup [--identity <name>] --app-id <id> --key <file.pem>`.

## Start sessions as the agent

```
scripts/agent-session.sh --persona build --worktree 0002-jd-extraction
scripts/agent-session.sh --persona dev
```

Everything after the persona goes to `claude`. In that session, `git` commits as `<app>[bot]` and pushes with the App's token; your SSH remote is rewritten to HTTPS for the session only. `gh` uses a fresh App token on each call. Nothing changes in your git config.

**Plain `claude` sessions use it too.** `.claude/settings.json` has a SessionStart hook (`scripts/agent-session.sh --hook`) that loads the same environment into every session's Bash commands. The wrapper is only needed to pick a persona (`--persona`) or to start a bug fix with its tests locked.

Without the App set up, both routes do nothing, and the session acts as you, as before.

## What stops agents looping or fighting

- **Agents start only when a person asks:** a terminal session, an `@claude` comment *written by a person*, or a merge to `main`. The mention workflow ignores comments from bots, the agent's own App included.
- **Agents never @-mention anyone** (the `agent-identity` skill), so they can't summon the mention bot or each other.
- **The review only comments.** A labelled PR is reviewed on each push, including the agent's pushes, but the review never pushes, so there's no loop. Findings wait for a person to work through them.
- **Before every push, fetch and merge.** A session checks the branch for commits it doesn't have, from a person, the bot or another session under the same identity, and merges them. It never rebases or force-pushes.
- **Approving and merging stay with people.** In team mode GitHub requires your approval, and the production-gate hook still blocks the agent from merging or approving.

## Notes

- **Tokens:** installation tokens last one hour, and the scripts renew them. The cache sits in `$XDG_RUNTIME_DIR` (memory-backed). The only long-lived secret is the private key, which stays in the keyring and in the repo's `SDLC_AGENT_APP_KEY` secret.
- **Rotating the key:** generate a new one on the App's page, re-run step 3 and `bootstrap-github.sh`, then delete the old key on GitHub.
- **Your own PRs in team mode:** a PR you open yourself needs someone else's approval. Open PRs through a Claude session instead (Claude is the author, you approve), or keep `--mode solo` for that repo.
- **Spec PRs** open as the App once its variables and secret are set. Their checks then run without the *Approve and run workflows* click.
