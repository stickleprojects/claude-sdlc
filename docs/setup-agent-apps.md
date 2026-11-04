# Setting up Claude's GitHub Apps: what you'll see

This is a walkthrough of `scripts/agent-identity.sh create`, the command that gives Claude its own GitHub identity in a repo, so its commits, PRs and review replies stop appearing under your name. For what the identity does and why, see [agent-identity.md](agent-identity.md).

**Run it once in each repo that uses the pipeline** (jobhunt-app, sdlc-sandbox, …). New Apps are named after the repo: `jobhunt-app-claude`, or `jobhunt-app-plan`, `jobhunt-app-build`, …. You can also **reuse** an App you already have, so one App can serve every repo and every persona (step 2).

It takes about 5 minutes for one App, plus about a minute for each extra App. You need a browser where you're signed in to GitHub as the repo's owner (for stickleprojects repos, your own account).

## 1. Start it, in the repo

```
cd ~/code/jobhunt-app
scripts/agent-identity.sh create
```

Nothing is created and no browser page opens until you've answered the questions and said yes.

## 2. (If you have Apps already) Reuse one?

When Claude already has Apps on this machine, from another repo or from a shared config, the first question offers them:

```
Claude already has GitHub Apps on this machine. Reuse one here?
  1) No: set up Apps for this repo (new ones, or a mix of new and existing)
  2) Yes: use jobhunt-app-claude for every persona (/home/you/.config/sdlc/stickleprojects_jobhunt-app/agent.env)
Choice [1]: 2

Reusing (nothing created, no key changed):
  jobhunt-app-claude                  for intent, spec, plan, build, dev, po-review  (/home/you/.config/sdlc/stickleprojects_jobhunt-app/agent.env)
A reused App must also be installed on this repo; you'll get the link.
Continue? [Y/n]
```

Choosing **2** points this repo at that App's config file. Nothing is created on GitHub, and no key is generated, copied or changed, so every repo using the App shares one App and one key. The terminal then prints the link for installing the App on this repo (`https://github.com/apps/jobhunt-app-claude/installations/new`); choose the repo there and click **Save**. Then go to step 11.

Choosing **1** goes on to the questions below. If you pick Apps per persona, each App can still be an existing one (step 7).

## 3. Name the Apps

```
Name prefix for this repo's Claude Apps [jobhunt-app]:
```

Press **Enter** to name them after the repo. Or type another name; it's made safe for GitHub (lowercase letters, digits and dashes), and you're told if it changed:

```
Name prefix for this repo's Claude Apps [jobhunt-app]: Job Hunt
  using job-hunt (lowercase letters, digits and dashes only)
```

App names are unique across all of GitHub. If `jobhunt-app-…` turns out to be taken, GitHub says so on its page in step 9. You can change the name there, or start again with a different prefix.

## 4. Choose how many Apps

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

## 5. (Apps per persona) Choose which personas get their own App

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

## 6. (Apps per persona) Choose which App each other persona shares

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

## 7. (If you have Apps already) New or existing, for each App

```
App for plan, intent, spec, po-review?
  1) new App (jobhunt-app-plan)
  2) existing jobhunt-app-claude (/home/you/.config/sdlc/stickleprojects_jobhunt-app/agent.env)
Choice [1]: 2
```

Any App can be an existing one; the summary then lists it under *Reusing*.

## 8. Check the summary and confirm

```

About to create 3 GitHub Apps:
  jobhunt-app-plan                    for plan, intent, spec, po-review
                                      config: /home/you/.config/sdlc/stickleprojects_jobhunt-app/agent-plan.env
  jobhunt-app-build                   for build  (can change .github/workflows)
                                      config: /home/you/.config/sdlc/stickleprojects_jobhunt-app/agent-build.env
  jobhunt-app-dev                     for dev  (can change .github/workflows)
                                      config: /home/you/.config/sdlc/stickleprojects_jobhunt-app/agent-dev.env
For each new App, your browser opens GitHub: click Create GitHub App, then install it on this repo.
Continue? [Y/n]
```

Press **Enter** or **y** to go ahead. **n** stops with `Nothing created.`

**Nothing is replaced without asking.** If a config already exists where one would be written, for example because this repo already has an App, you're shown the file and asked `Replace? [y/N]`. The App it named stays on GitHub, and its key isn't touched. Without a terminal, `create` stops instead, unless you pass `--force`.

## 9. In the browser, for each App

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

## 10. Back in the terminal

```
wrote the per-persona mapping to /home/you/.config/sdlc/stickleprojects_jobhunt-app/personas.conf
  agent-plan: jobhunt-app-plan[bot] (app 1234567), key in keyring (claude-sdlc GitHub App private key (stickleprojects_jobhunt-app agent-plan))
  agent-build: jobhunt-app-build[bot] (app 1234568), key in keyring (…)
  agent-dev: jobhunt-app-dev[bot] (app 1234569), key in keyring (…)
Next, in this repo: scripts/bootstrap-github.sh --mode team --skip-token
```

With one App, the first line reads `the repo's .claude/personas.conf applies (one App: agent)` instead.

**Where things are kept** (by default; see *Choosing where things live* below):

- **Private keys:** in your keyring, one entry per App, named after the App: *claude-sdlc GitHub App private key (jobhunt-app-plan)*. App names are unique on GitHub, so one App's key can never overwrite another's. Nothing is downloaded, so there's no `.pem` to delete.
- **App configs:** id, name, and where the key is (`SDLC_AGENT_KEY=keyring:…` or `file:…`), in `~/.config/sdlc/<owner>_<repo>/<identity>.env`. These aren't secret.
- **Which persona uses which App:** in `~/.config/sdlc/<owner>_<repo>/personas.conf`, only when you chose more than one App. It overrides the repo's `.claude/personas.conf`.

## 11. Finish the repo

```
scripts/bootstrap-github.sh --mode team --skip-token
```

Step 8 of the output checks each App can act on the repo. If it says `install … on <repo>`, use the link it prints. It also gives the spec workflow its App: the one `spec` uses. *Team mode* makes GitHub require your approval on every PR, now that Claude, not you, is the author.

To check: `scripts/agent-identity.sh check` prints `ok: a token for this repo was issued`.

From then on, every Claude session in this repo commits, pushes and comments as its App. A SessionStart hook in `.claude/settings.json` takes care of that.

## Choosing where things live

The default places are above. Everything can go elsewhere:

| You want | Use |
|---|---|
| **One App for every repo and persona** | Create it once (anywhere). In every other repo, run `create` and reuse it (step 2), or run `scripts/agent-identity.sh use <its config file>` |
| A new App's config in a file you name, e.g. one shared file | `create --config ~/claude/shared-claude.env` (one App) |
| Each new App's config in a folder you choose | `create --config-dir ~/claude/apps` (files named after the App, e.g. `jobhunt-app-plan.env`) |
| Keys as files instead of the keyring | `create --keys-dir ~/claude/keys` (one `<app>.pem` each, mode 600) |
| An App you made by hand, with its key in a file you keep | `setup --app-id <id> --key <downloaded.pem> --key-file ~/claude/keys/my-app.pem [--config <file>]` |
| Point a repo or persona at any config file on the machine | `use <file> [--identity agent-plan]` |

When a config lives somewhere other than the default place, the default place gets a one-line pointer to it (`SDLC_AGENT_USE=<file>`). So many repos and personas can point at one file, and changing that file (rotating its key, say) changes it for all of them. `use`, `setup` and `create` never replace an existing config or pointer without `--force` (or, in `create`, your yes).

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
