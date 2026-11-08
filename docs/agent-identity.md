# Claude's own GitHub identity

By default, Claude sessions use your `gh` login and your git credentials, so their commits, PRs and review replies appear under your name. This page sets up a separate identity, a GitHub App, so they appear as `<app>[bot]` instead. GitHub can then also require *your* approval before anything Claude wrote can merge.

## Who acts as whom

| Identity | Who | Where |
|---|---|---|
| `agent`: your App, `<repo>-claude[bot]` | every Claude Code session in this repo | local sessions |
| `agent` | the *Spec from intent* workflow | CI |
| `claude`: Anthropic's Claude App, `claude[bot]` | the review and `@claude` workflows | CI |

Claude never acts as you: comments are signed `— Claude`, and each commit carries a `Requested-by:` trailer naming the person who asked. The reviewer is a different identity from the author, so Claude never reviews as the account that wrote the code.

**More than one App later:** the identity name is a parameter (`SDLC_AGENT_IDENTITY_NAME`, `setup --identity <name>`), so a second App can be set up beside `agent` without changing it. Choosing which sessions use it would be new work; per-persona Apps were tried in claude-sdlc #61 and taken out to keep one identity.

## Set it up (once per repo, about 5 minutes)

For a step-by-step walkthrough with every prompt and page you'll see, read [setup-agent-apps.md](setup-agent-apps.md).

Each repo that uses the pipeline gets its own App, named after the repo: `jobhunt-app-claude`. Its key and config are kept per repo, so one repo's App never acts in another (unless you choose to share one).

1. **Create the App,** in the repo:
   ```
   scripts/agent-identity.sh create
   ```
   It asks before anything opens:
   - whether to **reuse an App** already on this machine (made for another repo), if there is one;
   - **the name prefix**, defaulting to the repo's name made safe for GitHub (lowercase letters, digits and dashes; at most 27 characters, so `-claude` fits GitHub's 34-character limit);
   - then it shows the App it will create and asks **Continue?**

   Then your browser opens GitHub's *Create GitHub App* page with everything filled in (name, permissions, no webhook, private). Click **Create GitHub App**, then on the install page pick this repo and click **Install**.

   It stores the App's private key in your keyring, under the App's name, and its config (id, name, where the key is) in `~/.config/sdlc/<owner>_<repo>/agent.env`, unless you choose other places.

   For scripts: `--name <prefix>` and `--yes`. Also `--org <org>` and `--no-browser`.

   **Permissions:** contents, pull requests, issues and workflows read and write; actions, checks, commit statuses, metadata and variables read.

   **An App created before variables read was added:** on the App's page, under *Permissions & events → Repository permissions*, set **Variables** to *Read-only* and save. Then accept the new permission on each installation (*Settings → GitHub Apps → Configure*, or the email GitHub sends). Until then `scripts/auto-merge.sh` warns that it can't read `SDLC_AUTO_MERGE`, and the PRs Claude opens from a session aren't auto-merged.
2. **Configure the repo:** `scripts/bootstrap-github.sh --mode team --skip-token`. Step 8 checks the App is installed, and gives the spec workflow the same App (the `SDLC_AGENT_APP_ID`/`_SLUG` variables and the `SDLC_AGENT_APP_KEY` secret). Team mode makes GitHub require a code owner's (your) approval on every PR.
3. **Check:** `scripts/agent-identity.sh check` should print `ok: a token for this repo was issued`.

**Another repo:** run the same three steps there. To use **the same App** there (or for every repo), reuse it when `create` offers it, or run `scripts/agent-identity.sh use <its config file>`, then install the App on the repo.

**Nothing overwrites anything.** Keys are stored under the App's own name, which is unique on GitHub. A config records where its key is, so repos sharing an App share one key. `create`, `setup` and `use` never replace an existing config without asking (`--force` when scripted). Configs and keys can live anywhere (`--config`, `--config-dir`, `--keys-dir`, `--key-file`, `use <file>`); see [setup-agent-apps.md](setup-agent-apps.md#choosing-where-things-live).

**By hand instead:** create the App under *Settings → Developer settings → GitHub Apps* with the permissions above, generate a private key, install it on the repo, and run `scripts/agent-identity.sh setup [--identity <name>] --app-id <id> --key <file.pem>` in that repo.

## Start sessions as the agent

```
scripts/agent-session.sh --worktree 0002-jd-extraction
```

Everything goes on to `claude`. In that session, `git` commits as `<app>[bot]` and pushes with the App's token; your SSH remote is rewritten to HTTPS for the session only. `gh` uses a fresh App token on each call. Nothing changes in your git config.

**Plain `claude` sessions use it too.** `.claude/settings.json` has a SessionStart hook (`scripts/agent-session.sh --hook`) that loads the same environment into every session's Bash commands. The wrapper is only needed to say, at the start, whether a bug fix's tests are locked.

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
