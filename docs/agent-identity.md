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

To give a persona its own App later, add an `identity` line in `personas.conf`, point the persona at it, and run `setup --identity <name>` (step 3).

## Set it up (once, about 10 minutes)

1. **Create the App.** On GitHub go to **Settings → Developer settings → GitHub Apps → New GitHub App**.
   - **Name:** e.g. `stickle-claude`. The bot shows as `stickle-claude[bot]`.
   - **Homepage URL:** the claude-sdlc repo.
   - **Webhook:** untick *Active*.
   - **Repository permissions:**
     - *Contents*: read and write;
     - *Pull requests*: read and write;
     - *Issues*: read and write (labels, comments);
     - *Workflows*: read and write (only needed where Claude edits `.github/workflows/`);
     - *Actions*: read; *Checks*: read; *Commit statuses*: read; *Metadata*: read.
   - **Where can this app be installed:** *Only on this account*.
   - Create it, note the **App ID**, then **Generate a private key**. A `.pem` file downloads.
2. **Install it** on each repo that uses the pipeline: the App's page → **Install App** → *Only select repositories*.
3. **Store the key on your machine:**
   ```
   scripts/agent-identity.sh setup --app-id <App ID> --key ~/Downloads/<app>.<date>.private-key.pem
   ```
   This puts the key in your keyring (Seahorse shows it as *claude-sdlc GitHub App private key (agent)*) and writes the non-secret details to `~/.config/sdlc/agent.env`. Then delete the downloaded `.pem`.
4. **Configure each repo:** `scripts/bootstrap-github.sh --mode team --skip-token`. Step 8 checks the App is installed, and sets the `SDLC_AGENT_APP_ID` and `SDLC_AGENT_APP_SLUG` variables and the `SDLC_AGENT_APP_KEY` secret that the workflows use. Team mode makes GitHub require a code owner's (your) approval on every PR.
5. **Check:** `scripts/agent-identity.sh check` should print `ok: a token for this repo was issued`.

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
