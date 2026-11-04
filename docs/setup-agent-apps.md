# Setting up Claude's GitHub Apps: what you'll see

This is a walkthrough of `scripts/agent-identity.sh create`, the command that gives Claude its own GitHub identity in a repo, so its commits, PRs and review replies stop appearing under your name. For what the identity does and why, see [agent-identity.md](agent-identity.md).

**Run it once in each repo that uses the pipeline** (jobhunt-app, sdlc-sandbox, …). The Apps belong to that repo and are named after it: `jobhunt-app-claude`, or `jobhunt-app-plan`, `jobhunt-app-build`, ….

It takes about 5 minutes for one App, plus about a minute for each extra App. You need a browser where you're signed in to GitHub as the repo's owner (for stickleprojects repos, your own account).

## 1. Start it, in the repo

```
cd ~/code/jobhunt-app
scripts/agent-identity.sh create
```

Nothing is created and no browser page opens until you've answered the questions and said yes.

## 2. Name the Apps

```
Name prefix for this repo's Claude Apps [jobhunt-app]:
```

Press **Enter** to name them after the repo. Or type another name; it's made safe for GitHub (lowercase letters, digits and dashes), and you're told if it changed:

```
Name prefix for this repo's Claude Apps [jobhunt-app]: Job Hunt
  using job-hunt (lowercase letters, digits and dashes only)
```

App names are unique across all of GitHub. If `jobhunt-app-…` turns out to be taken, GitHub says so on its page in step 7. You can change the name there, or start again with a different prefix.

## 3. Choose how many Apps

```
How many GitHub Apps should Claude use?
  1) One App for everything (jobhunt-app-claude): every persona signs as itself (recommended)
  2) Apps per persona: choose which personas get their own App; the rest share one of them
Choice [1]:
```

Press **Enter** for one App. Each comment is still signed with its persona, e.g. `— Claude (build)`, so you can tell them apart without separate Apps. You'll go straight to the summary:

```

About to create 1 GitHub App:
  jobhunt-app-claude                  for intent, spec, plan, build, dev, po-review  (can change .github/workflows)
For each one, your browser opens GitHub: click Create GitHub App, then install it on this repo.
Continue? [Y/n]
```

Choose **2** to split the personas over several Apps. Each App gets only the permissions its personas need: only Apps serving `build` or `dev` may change `.github/workflows/`.

## 4. (Apps per persona) Choose which personas get their own App

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

## 5. (Apps per persona) Choose which App each other persona shares

```
intent: which App does it share?
  1) jobhunt-app-plan
  2) jobhunt-app-build
  3) jobhunt-app-dev
Choice [1]: 1

spec: which App does it share?
  1) jobhunt-app-plan
  2) jobhunt-app-build
  3) jobhunt-app-dev
Choice [1]: 1

po-review: which App does it share?
  1) jobhunt-app-plan
  2) jobhunt-app-build
  3) jobhunt-app-dev
Choice [1]: 1
```

An answer that isn't one of the numbers gets the question asked again.

## 6. Check the summary and confirm

```

About to create 3 GitHub Apps:
  jobhunt-app-plan                    for plan, intent, spec, po-review
  jobhunt-app-build                   for build  (can change .github/workflows)
  jobhunt-app-dev                     for dev  (can change .github/workflows)
For each one, your browser opens GitHub: click Create GitHub App, then install it on this repo.
Continue? [Y/n]
```

Press **Enter** or **y** to go ahead. **n** stops with `Nothing created.`

## 7. In the browser, for each App

The terminal prints a local address, and your browser opens it:

```
Open http://127.0.0.1:40213/start if your browser doesn't. If you skip an install page, open .../next.
```

For each App, in order:

1. **A short local page**, *Create jobhunt-app-plan (1 of 3)*, saying which personas it's for. It passes you straight on to GitHub; if it doesn't, click **Continue to GitHub**.
2. **GitHub's "Create GitHub App" page**, already filled in: name, permissions, no webhook, private to your account. Click **Create GitHub App**. If the name is taken, change it there.
3. **GitHub's install page** for the new App. Choose **Only select repositories**, pick **this repo** (jobhunt-app), then click **Install**.
4. GitHub sends you back to the local page, which moves on to the next App.

Meanwhile, the terminal confirms each one as it's created:

```
  created jobhunt-app-plan (app 1234567); config /home/you/.config/sdlc/stickleprojects_jobhunt-app/agent-plan.env
```

After the last App, the browser shows **All done**, with a list of the Apps, and *Back to the terminal.*

## 8. Back in the terminal

```
wrote the per-persona mapping to /home/you/.config/sdlc/stickleprojects_jobhunt-app/personas.conf
  agent-plan: jobhunt-app-plan[bot] (app 1234567), key in keyring (claude-sdlc GitHub App private key (stickleprojects_jobhunt-app agent-plan))
  agent-build: jobhunt-app-build[bot] (app 1234568), key in keyring (…)
  agent-dev: jobhunt-app-dev[bot] (app 1234569), key in keyring (…)
Next, in this repo: scripts/bootstrap-github.sh --mode team --skip-token
```

With one App, the first line reads `the repo's .claude/personas.conf applies (one App: agent)` instead.

**Where things are kept,** separately for each repo, so jobhunt-app's Apps never act in sdlc-sandbox:

- **Private keys:** in your keyring. Seahorse shows each as *claude-sdlc GitHub App private key (<owner>_<repo> <identity>)*. Nothing is downloaded, so there's no `.pem` to delete.
- **App ids and names:** in `~/.config/sdlc/<owner>_<repo>/<identity>.env`. These aren't secret.
- **Which persona uses which App:** in `~/.config/sdlc/<owner>_<repo>/personas.conf`, only when you chose more than one App. It overrides the repo's `.claude/personas.conf`.

## 9. Finish the repo

```
scripts/bootstrap-github.sh --mode team --skip-token
```

Step 8 of the output checks each App can act on the repo. If it says `install … on <repo>`, use the link it prints. It also gives the spec workflow its App: the one `spec` uses. *Team mode* makes GitHub require your approval on every PR, now that Claude, not you, is the author.

To check: `scripts/agent-identity.sh check` prints `ok: a token for this repo was issued`.

From then on, every Claude session in this repo commits, pushes and comments as its App. A SessionStart hook in `.claude/settings.json` takes care of that.

## Changing your mind later

- **Different grouping or name:** run `create` again in the repo and answer differently. Apps you no longer use can be deleted on GitHub (*Settings → Developer settings → GitHub Apps → the App → Advanced → Delete*).
- **Back to one App:** run `create` and choose 1. The per-persona mapping is moved aside to `personas.conf.bak`.

## Without prompts (scripts, CI machines)

```
scripts/agent-identity.sh create --name jobhunt-app --per-persona --yes
scripts/agent-identity.sh create --name jobhunt-app --groups "plan+intent+spec+po-review,build,dev" --yes
```

Without a terminal and without `--name`, the prefix is the repo's name. In `--groups`, each group shares one App, named after its first persona. Other options:

- `--org <org>` creates the Apps under an organization;
- `--no-browser` only prints the address.
