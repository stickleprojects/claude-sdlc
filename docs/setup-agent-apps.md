# Setting up Claude's GitHub Apps: what you'll see

This is a walkthrough of `scripts/agent-identity.sh create`, the command that gives Claude its own GitHub identity, so its commits, PRs and review replies stop appearing under your name. For what the identity does and why, see [agent-identity.md](agent-identity.md).

It takes about 5 minutes for one App, plus about a minute for each extra App. You need a browser where you're signed in to GitHub as the account that will own the Apps (for stickleprojects, your own account).

## 1. Start it

From any repo that has the pipeline:

```
scripts/agent-identity.sh create
```

Nothing is created and no browser page opens until you've answered the questions and said yes.

## 2. Choose how many Apps

```
How many GitHub Apps should Claude use?
  1) One App for everything (stickleprojects-claude): every persona signs as itself (recommended)
  2) Apps per persona: choose which personas get their own App; the rest share one of them
Choice [1]:
```

Press **Enter** for one App. Each comment is still signed with its persona, e.g. `— Claude (build)`, so you can tell them apart without separate Apps. You'll go straight to the summary:

```

About to create 1 GitHub App:
  stickleprojects-claude              for intent, spec, plan, build, dev, po-review  (can change .github/workflows)
For each one, your browser opens GitHub: click Create GitHub App, then install it on your repos.
Continue? [Y/n]
```

Choose **2** to split the personas over several Apps. Each App gets only the permissions its personas need: only Apps serving `build` or `dev` may change `.github/workflows/`.

## 3. (Apps per persona) Choose which personas get their own App

```
Which personas get an App of their own?
  1) intent
  2) spec
  3) plan
  4) build
  5) dev
  6) po-review
Numbers, comma-separated [all]: 3,4,5
```

Press **Enter** to give every persona its own App (six Apps). Otherwise list the ones that should own an App. Here, `plan`, `build` and `dev` do.

## 4. (Apps per persona) Choose which App each other persona shares

For each persona you didn't pick, choose which of those Apps it uses:

```
intent: which App does it share?
  1) stickleprojects-claude-plan
  2) stickleprojects-claude-build
  3) stickleprojects-claude-dev
Choice [1]: 1

spec: which App does it share?
  1) stickleprojects-claude-plan
  2) stickleprojects-claude-build
  3) stickleprojects-claude-dev
Choice [1]: 1

po-review: which App does it share?
  1) stickleprojects-claude-plan
  2) stickleprojects-claude-build
  3) stickleprojects-claude-dev
Choice [1]: 1
```

An answer that isn't one of the numbers gets the question asked again.

## 5. Check the summary and confirm

```

About to create 3 GitHub Apps:
  stickleprojects-claude-plan         for plan, intent, spec, po-review
  stickleprojects-claude-build        for build  (can change .github/workflows)
  stickleprojects-claude-dev          for dev  (can change .github/workflows)
For each one, your browser opens GitHub: click Create GitHub App, then install it on your repos.
Continue? [Y/n]
```

Press **Enter** or **y** to go ahead. **n** stops with `Nothing created.`

## 6. In the browser, for each App

The terminal prints a local address, and your browser opens it:

```
Open http://127.0.0.1:40213/start if your browser doesn't. If you skip an install page, open .../next.
```

For each App, in order:

1. **A short local page**, *Create stickleprojects-claude-plan (1 of 3)*, saying which personas it's for. It passes you straight on to GitHub; if it doesn't, click **Continue to GitHub**.
2. **GitHub's "Create GitHub App" page**, already filled in: name, permissions, no webhook, private to your account. Click **Create GitHub App for stickleprojects**. If the name is taken (App names are unique across all of GitHub), change it there, or start again with `--name <prefix>`.
3. **GitHub's install page** for the new App. Choose **Only select repositories**, pick the repos Claude works in (e.g. claude-sdlc, jobhunt-app, sdlc-sandbox), then click **Install**.
4. GitHub sends you back to the local page, which moves on to the next App.

Meanwhile, the terminal confirms each one as it's created:

```
  created stickleprojects-claude-plan (app 1234567); config /home/you/.config/sdlc/agent-plan.env
```

After the last App, the browser shows **All done**, with a list of the Apps, and *Back to the terminal.*

## 7. Back in the terminal

```
wrote the per-persona mapping to /home/you/.config/sdlc/personas.conf
  agent-plan: stickleprojects-claude-plan[bot] (app 1234567), key in keyring (claude-sdlc GitHub App private key (agent-plan))
  agent-build: stickleprojects-claude-build[bot] (app 1234568), key in keyring (claude-sdlc GitHub App private key (agent-build))
  agent-dev: stickleprojects-claude-dev[bot] (app 1234569), key in keyring (claude-sdlc GitHub App private key (agent-dev))
Next, in each repo: scripts/bootstrap-github.sh --mode team --skip-token
```

With one App, the first line reads `the repo's .claude/personas.conf applies (one App: agent)` instead.

**Where things are kept:**

- **Private keys:** in your keyring. Seahorse shows each as *claude-sdlc GitHub App private key (…)*. Nothing is downloaded, so there's no `.pem` to delete.
- **App ids and names:** in `~/.config/sdlc/<identity>.env`. These aren't secret.
- **Which persona uses which App:** in `~/.config/sdlc/personas.conf`, only when you chose more than one App. It overrides the repo's `.claude/personas.conf`.

## 8. Finish each repo

In each repo the Apps are installed on:

```
scripts/bootstrap-github.sh --mode team --skip-token
```

Step 8 of the output checks each App can act on that repo. If it says `install … on <repo>`, use the link it prints. It also gives the spec workflow its App: the one `spec` uses. *Team mode* makes GitHub require your approval on every PR, now that Claude, not you, is the author.

To check a repo: `scripts/agent-identity.sh check` prints `ok: a token for this repo was issued`.

From then on, every Claude session in those repos commits, pushes and comments as the App. A SessionStart hook in `.claude/settings.json` takes care of that.

## Changing your mind later

- **Different grouping:** run `create` again and answer differently. The Apps you no longer use can be deleted on GitHub (*Settings → Developer settings → GitHub Apps → the App → Advanced → Delete*).
- **Back to one App:** run `create` and choose 1. The per-persona mapping is moved aside to `personas.conf.bak`.
- **Another repo:** install the App(s) on it from the App's page (*Install App → Configure*), then run step 8 there.

## Without prompts (scripts, CI machines)

```
scripts/agent-identity.sh create --per-persona --yes                                   # one App each
scripts/agent-identity.sh create --groups "plan+intent+spec+po-review,build,dev" --yes  # the example above
```

In `--groups`, each group shares one App, named after its first persona. Other options:

- `--name <prefix>` changes the App names;
- `--org <org>` creates the Apps under an organization;
- `--no-browser` only prints the address.
