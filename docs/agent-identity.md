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

## Set it up (once per repo, about 5 minutes)

For a step-by-step walkthrough with every prompt and page you'll see, read [setup-agent-apps.md](setup-agent-apps.md).

Each repo that uses the pipeline gets its own App(s), named after the repo: `jobhunt-app-claude`, or `jobhunt-app-plan`, `jobhunt-app-build`, …. Keys, config and the persona mapping are kept per repo, so one repo's Apps never act in another.

1. **Create the App or Apps,** in the repo:
   ```
   scripts/agent-identity.sh create
   ```
   It asks before anything opens:
   - **the name prefix**, defaulting to the repo's name made safe for GitHub (lowercase letters, digits and dashes; at most 24 characters, so `-po-review` still fits GitHub's 34-character limit);
   - **one App for everything** (`<prefix>-claude`, recommended), or **Apps per persona** (`<prefix>-<persona>`);
   - with Apps per persona: **which personas get an App of their own** (e.g. plan, build, dev), then **which of those Apps each other persona shares** (e.g. intent, spec and po-review share plan's);
   - then it lists the Apps it will create, who each serves and which can change workflows, and asks **Continue?**

   Then, for each App, your browser opens GitHub's *Create GitHub App* page with everything filled in (name, permissions, no webhook, private). Click **Create GitHub App**, then on the install page pick this repo and click **Install**. GitHub sends you back for the next App.

   It stores each App's private key in your keyring, under the App's name, and its config (id, name, where the key is) in `~/.config/sdlc/<owner>_<repo>/<identity>.env`, unless you choose other places. With more than one App it also writes `~/.config/sdlc/<owner>_<repo>/personas.conf`, which maps each persona to its App and overrides the repo's copy.

   For scripts: `--name <prefix>`, `--per-persona` or `--groups "plan+intent+spec+po-review,build,dev"`, and `--yes`. Also `--org <org>` and `--no-browser`.

   **Permissions:** contents, pull requests and issues read and write; actions, checks, commit statuses and metadata read. Workflows write goes only to the App that serves `build` or `dev`.
2. **Configure the repo:** `scripts/bootstrap-github.sh --mode team --skip-token`. Step 8 checks each App is installed, and gives the workflows the App that `spec-ci` uses (the `SDLC_AGENT_APP_ID`/`_SLUG` variables and the `SDLC_AGENT_APP_KEY` secret). Team mode makes GitHub require a code owner's (your) approval on every PR.
3. **Check:** `scripts/agent-identity.sh check` should print `ok: a token for this repo was issued`.

**Another repo:** run the same three steps there. To use **the same App** there (or for every repo), reuse it when `create` offers it, or run `scripts/agent-identity.sh use <its config file>`, then install the App on the repo.

**Nothing overwrites anything.** Keys are stored under the App's own name, which is unique on GitHub. A config records where its key is, so repos sharing an App share one key. `create`, `setup` and `use` never replace an existing config without asking (`--force` when scripted). Configs and keys can live anywhere (`--config`, `--config-dir`, `--keys-dir`, `--key-file`, `use <file>`); see [setup-agent-apps.md](setup-agent-apps.md#choosing-where-things-live).

**By hand instead:** create the App under *Settings → Developer settings → GitHub Apps* with the permissions above, generate a private key, install it on the repo, and run `scripts/agent-identity.sh setup [--identity <name>] --app-id <id> --key <file.pem>` in that repo.

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
- **The review only comments.** It runs when a PR opens and when someone adds the `review` label, including on the agent's PRs, but it never pushes, so there's no loop. Findings wait for a person to work through them.
- **Before every push, fetch and merge.** A session checks the branch for commits it doesn't have, from a person, the bot or another session under the same identity, and merges them. It never rebases or force-pushes.
- **Approving and merging stay with people.** In team mode GitHub requires your approval, and the production-gate hook still blocks the agent from merging or approving.

## Notes

- **Tokens:** installation tokens last one hour, and the scripts renew them. The cache sits in `$XDG_RUNTIME_DIR` (memory-backed). The only long-lived secret is the private key, which stays in the keyring and in the repo's `SDLC_AGENT_APP_KEY` secret.
- **Rotating the key:** generate a new one on the App's page, re-run step 3 and `bootstrap-github.sh`, then delete the old key on GitHub.
- **Your own PRs in team mode:** a PR you open yourself needs someone else's approval. Open PRs through a Claude session instead (Claude is the author, you approve), or keep `--mode solo` for that repo.
- **Spec PRs** open as the App once its variables and secret are set. Their checks then run without the *Approve and run workflows* click.
