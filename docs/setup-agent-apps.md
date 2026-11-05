# Setting up Claude's GitHub App: what you'll see

This is a walkthrough of `scripts/agent-identity.sh create`, the command that gives Claude its own GitHub identity in a repo, so its commits, PRs and review replies stop appearing under your name. For what the identity does and why, see [agent-identity.md](agent-identity.md).

**Run it once in each repo that uses the pipeline** (jobhunt-app, sdlc-sandbox, …). A new App is named after the repo: `jobhunt-app-claude`. You can also **reuse** an App you already have, so one App can serve every repo (step 2).

It takes about 5 minutes. You need a browser where you're signed in to GitHub as the repo's owner (for stickleprojects repos, your own account).

## 1. Start it, in the repo

```
cd ~/code/jobhunt-app
scripts/agent-identity.sh create
```

Nothing is created and no browser page opens until you've answered the questions and said yes.

## 2. (If you have Apps already) Reuse one?

When Claude already has an App on this machine, from another repo or from a shared config, the first question offers it:

```
Claude already has GitHub Apps on this machine. Reuse one here?
  1) No: create a new App for this repo
  2) Yes: use jobhunt-app-claude (/home/you/.config/sdlc/stickleprojects_jobhunt-app/agent.env)
Choice [1]: 2

Reusing (nothing created, no key changed):
  jobhunt-app-claude                  (/home/you/.config/sdlc/stickleprojects_jobhunt-app/agent.env)
A reused App must also be installed on this repo; you'll get the link.
Continue? [Y/n]
```

Choosing **2** points this repo at that App's config file. Nothing is created on GitHub, and no key is generated, copied or changed, so every repo using the App shares one App and one key. The terminal then prints the link for installing the App on this repo (`https://github.com/apps/jobhunt-app-claude/installations/new`); choose the repo there and click **Save**. Then go to step 7.

Choosing **1** goes on to the questions below.

## 3. Name the App

```
Name prefix for this repo's Claude Apps [jobhunt-app]:
```

Press **Enter** to name it after the repo (`jobhunt-app-claude`). Or type another name; it's made safe for GitHub (lowercase letters, digits and dashes), and you're told if it changed:

```
Name prefix for this repo's Claude Apps [jobhunt-app]: Job Hunt
  using job-hunt (lowercase letters, digits and dashes only)
```

App names are unique across all of GitHub. If the name turns out to be taken, GitHub says so on its page in step 5. You can change the name there, or start again with a different prefix.

## 4. Check the summary and confirm

```

About to create 1 GitHub App, for every Claude session in this repo:
  jobhunt-app-claude                  (can change .github/workflows)
                                      config: /home/you/.config/sdlc/stickleprojects_jobhunt-app/agent.env
Your browser opens GitHub: click Create GitHub App, then install it on this repo.
Continue? [Y/n]
```

Press **Enter** or **y** to go ahead. **n** stops with `Nothing created.`

**Nothing is replaced without asking.** If a config already exists where one would be written, for example because this repo already has an App, you're shown the file and asked `Replace? [y/N]`. The App it named stays on GitHub, and its key isn't touched. Without a terminal, `create` stops instead, unless you pass `--force`.

## 5. In the browser

The terminal prints a local address, and your browser opens it:

```
Open http://127.0.0.1:40213/start if your browser doesn't. If you skip an install page, open .../next.
```

1. **A short local page**, *Create jobhunt-app-claude (1 of 1)*. It passes you straight on to GitHub; if it doesn't, click **Continue to GitHub**.
2. **GitHub's "Create GitHub App" page**, already filled in: name, permissions, no webhook, private to your account. Click **Create GitHub App**. If the name is taken, change it there.
3. **GitHub's install page** for the new App. Choose **Only select repositories**, pick **this repo** (jobhunt-app), then click **Install**.
4. GitHub sends you back to the local page, which shows **All done**. *Back to the terminal.*

Meanwhile, the terminal confirms it:

```
  created jobhunt-app-claude (app 1234567); config /home/you/.config/sdlc/stickleprojects_jobhunt-app/agent.env
```

## 6. Back in the terminal

```
  agent: jobhunt-app-claude[bot] (app 1234567), key at keyring:github-app-private-key:jobhunt-app-claude
Next, in this repo: scripts/bootstrap-github.sh --mode team --skip-token
```

**Where things are kept** (by default; see *Choosing where things live* below):

- **The private key:** in your keyring, named after the App: *claude-sdlc GitHub App private key (jobhunt-app-claude)*. App names are unique on GitHub, so one App's key can never overwrite another's. Nothing is downloaded, so there's no `.pem` to delete.
- **The App's config:** id, name, and where the key is (`SDLC_AGENT_KEY=keyring:…` or `file:…`), in `~/.config/sdlc/<owner>_<repo>/agent.env`. It isn't secret.

## 7. Finish the repo

```
scripts/bootstrap-github.sh --mode team --skip-token
```

Step 8 of the output checks the App can act on the repo. If it says `install … on <repo>`, use the link it prints. It also gives the spec workflow the same App. *Team mode* makes GitHub require your approval on every PR, now that Claude, not you, is the author.

To check: `scripts/agent-identity.sh check` prints `ok: a token for this repo was issued`.

From then on, every Claude session in this repo commits, pushes and comments as the App. A SessionStart hook in `.claude/settings.json` takes care of that.

## Choosing where things live

The default places are above. Everything can go elsewhere:

| You want | Use |
|---|---|
| **One App for every repo** | Create it once (anywhere). In every other repo, run `create` and reuse it (step 2), or run `scripts/agent-identity.sh use <its config file>` |
| The new App's config in a file you name, e.g. one shared file | `create --config ~/claude/shared-claude.env` |
| The new App's config in a folder you choose | `create --config-dir ~/claude/apps` (named after the App, e.g. `jobhunt-app-claude.env`) |
| The key as a file instead of the keyring | `create --keys-dir ~/claude/keys` (`<app>.pem`, mode 600) |
| An App you made by hand, with its key in a file you keep | `setup --app-id <id> --key <downloaded.pem> --key-file ~/claude/keys/my-app.pem [--config <file>]` |
| Point a repo at any config file on the machine | `use <file>` |

When a config lives somewhere other than the default place, the default place gets a one-line pointer to it (`SDLC_AGENT_USE=<file>`). So many repos can point at one file, and changing that file (rotating its key, say) changes it for all of them. `use`, `setup` and `create` never replace an existing config or pointer without `--force` (or, in `create`, your yes).

## When something goes wrong

Start with:

```
scripts/agent-identity.sh doctor
```

It checks each link in turn: the config, the key, whether GitHub accepts the key, whether the App is installed on this repo, and a token. It stops at the first broken one, with the fix:

| What you see | What it means | What to do |
|---|---|---|
| GitHub says **"Name has already been taken"** while creating | You (or someone) made an App with that name before | Keep it: on its page (`https://github.com/settings/apps/<name>`) click **Generate a private key**, then `scripts/agent-identity.sh setup --app-id <its App ID> --key <the .pem>`. Or delete it there (*Advanced → Delete GitHub App*) and run `create` again, or use another name. Skip the App on the local page (*skip this App*), and the terminal prints these options. |
| The local page says **"GitHub didn't hand over the App"** | The App was made, but the one-time code expired (codes last an hour, and work once), timed out or came back incomplete. Nothing was saved | Same options as above (the App may exist without its key), or **Try again** |
| GitHub asks you to **sign in** and then shows an empty form | The pre-filled form didn't survive the sign-in | Go back to the local page and continue again |
| GitHub says you **can't create Apps** (organizations) | Creating Apps in an organization needs an owner or "App manager" | Ask an owner, or create it under your own account (drop `--org`) |
| `GitHub rejected …'s credentials` | The key was deleted or replaced on GitHub, the App id is wrong, the App was deleted, or the clock is off | `doctor` tells which. **A new key doesn't mean a new App:** see *Replacing a key* below. Only a deleted App needs `create --force` |
| `… isn't installed on <repo>` | The App exists but this repo isn't in its installation | Use the link it prints, add the repo, **Save** |
| `installation … suspended` | Someone suspended the App's installation | Unsuspend it at https://github.com/settings/installations |
| `didn't answer after 3 tries`, `had an error (5xx)` | Network trouble or a GitHub outage (each call is tried 3 times) | Try again later; https://www.githubstatus.com |

### Replacing a key (without deleting the App)

An App can have several private keys, and an old key keeps working until you delete it. So a key can be replaced safely, and only deliberately:

1. On the App's page, `https://github.com/settings/apps/<name>`, under *Private keys*, click **Generate a private key**. A `.pem` downloads. GitHub has no API for this, so it can't happen by accident.
2. Run `scripts/agent-identity.sh rekey --key <the .pem>`. It checks first that GitHub accepts the key **for that App**, and refuses anything else. Then it asks before replacing the stored key, because every repo sharing the App uses it. Scripted: add `--yes`.
3. Update CI in each repo that uses the App: `scripts/bootstrap-github.sh --update-agent-key --skip-token`.
4. Delete the old key on the App's page, and the downloaded `.pem`.

Deleting and re-creating the App is only needed when the App itself has been deleted.

## Without prompts (scripts, CI machines)

```
scripts/agent-identity.sh create --name jobhunt-app --yes
```

Without a terminal and without `--name`, the prefix is the repo's name. Other options:

- `--org <org>` creates the App under an organization;
- `--no-browser` only prints the address.
