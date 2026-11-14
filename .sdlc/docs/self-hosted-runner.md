# Running the pipeline on your own runner

The pipeline's workflows run on GitHub-hosted runners (`ubuntu-latest`) by default. One repository variable, `SDLC_RUNNER`, moves every framework job to a runner of your own. People use it for two reasons:

- **For a while,** when GitHub's runners are down or queued. Every required check waits on them, so no PR can merge. Delete the variable when they're back.
- **For good,** to stop paying for Actions minutes. A private repo's free minutes run out, and with a $0 budget, jobs sit in `queued` without an error. The runner and the variable stay.

## Switch over

1. **Lock the repo down first** (see [Keep strangers off your runner](#keep-strangers-off-your-runner)).
2. **Register the runner** (Settings → Actions → Runners → New self-hosted runner). On a repo owned by a personal account, it goes on the repo, since there are no org runners. It gets the label `self-hosted`.
3. **Set the variable:**

   ```
   gh variable set SDLC_RUNNER --body self-hosted
   ```

   The value is one runner label. Runs that were already queued don't move: re-run them (`gh run rerun <id>`), or push a commit.
4. **To go back to GitHub's runners:** `gh variable delete SDLC_RUNNER`. If the runner was only for an outage, remove it too (Settings → Actions → Runners).

Each job asks for:

```yaml
runs-on: ${{ vars.SDLC_RUNNER && !github.event.issue.pull_request && (!github.event.pull_request || github.event.pull_request.head.repo.full_name == github.repository) && vars.SDLC_RUNNER || 'ubuntu-latest' }}
```

In words, the job uses `SDLC_RUNNER` when it's set, except in these cases, which go to GitHub-hosted runners:
- PRs from forks;
- PRs whose fork has since been deleted;
- comments on any PR.

Each of these can run code that nobody with access to the repo wrote. Comments go to GitHub's runners because a comment event doesn't say where the PR came from. The `@claude` mention bot isn't a required check, so during an outage that only delays its reply.

## A runner that runs one job at a time

A single runner, such as a developer's laptop, runs each PR push's jobs one after the other. `make check` can take many minutes, and when it starts first, the Claude review waits behind it. When the review then asks for changes, that `check` run was wasted: the push is going to be redone.

To run `check` only after a clean review, set:

```
gh variable set SDLC_CHECK_AFTER_REVIEW --body on
```

A review that asks for changes then never costs a `check` run ([settings.md](settings.md) has the details). Use it with `SDLC_AUTO_MERGE`, which reviews every push.

## What the runner needs

- Linux with `bash`, `git`, `make`, `curl` and `jq`, plus the `gh` CLI (the review and merge scripts call it).
- **A writable home directory** for the runner's user: toolchains and caches go into `~/.cache` and `~/.local`. This is easy to miss when the runner has its own user, as recommended below.
- Whatever the repo's `.github/actions/setup-stack/` expects to find rather than installs itself. claude-sdlc's installs `uv` with `astral-sh/setup-uv`, so it needs nothing more. Other stacks differ. For example, one that makes a virtualenv needs `python3` with its `venv` module (on Debian and Ubuntu, the separate `python3-venv` package). One that downloads and checks a toolchain needs `unzip` and `sha512sum`.
- `node` and `npm` on the `PATH`, for the jobs that run Claude Code outside the action (spec from intent, the clause check, agent evals). `.sdlc/scripts/install-claude.sh` installs a pinned version into the job's `$RUNNER_TEMP`, never globally, so it can't collide with the `claude` that `claude-code-action` leaves in `~/.local/bin` or leak into other jobs (#136). The JavaScript actions need nothing: the runner brings its own Node for them, and `claude-code-action` installs Bun itself.
- `actions/cache` works, but it saves to GitHub's cache service, so the runner still needs to reach GitHub.

Change the runner service's user between jobs, never during one. A job that's running when the service restarts fails with "The runner has received a shutdown signal".

## Allowed actions

If Settings → Actions → General → Actions permissions limits which actions may run, list every action the workflows use, **including the ones used inside other actions**. A blocked action fails the job at startup ("This run likely failed because of a workflow file issue"). The framework's workflows need:

```
actions/checkout@*, actions/create-github-app-token@*, actions/upload-artifact@*, anthropics/claude-code-action@*, oven-sh/setup-bun@*, astral-sh/setup-uv@*
```

- `oven-sh/setup-bun` is used inside `claude-code-action`, so without it both Claude jobs fail.
- `actions/upload-artifact` keeps a failed Claude review's output (#157). Without it the review workflow doesn't start.
- The sync checks this list against the workflows it installs and names any action that's missing.
- `astral-sh/setup-uv` is only needed if your `setup-stack` uses it.
- Add the actions your repo's own workflows and `setup-stack` use (for example `actions/cache`).
- Your repo's own composite actions (`./.github/actions/*`) count as the owner's, so the owner's actions must be allowed.

"Local actions only" blocks `actions/checkout` too, so every job fails.

## Keep strangers off your runner

**On a public repo,** anyone can open a PR from a fork. A PR's workflows run from the PR's own copy of the workflow files, so the rule in `runs-on` only holds while nobody edits it. A fork PR can change `runs-on` to `self-hosted` and run anything on your machine. These keep it out:

1. **Approve every fork PR's workflows yourself.** Settings → Actions → General → *Approval for running fork pull request workflows from contributors* → **Require approval for all external contributors**. Or from the command line:

   ```
   gh api -X PUT repos/<owner>/<repo>/actions/permissions/fork-pr-contributor-approval \
     -f approval_policy=all_external_contributors
   ```

   After that, no fork PR's workflow runs anywhere until a maintainer clicks *Approve and run workflows*. Read the PR's workflow changes before you click. The sync warns when `SDLC_RUNNER` is set on a public repo without this setting. It can only check this with a login that can read the repo's Actions settings (an admin's), so run as the agent App, it says "not checked".
2. **Give write access only to people you trust.** Collaborators can push branches to the repo itself, and those runs don't ask for approval.

**On a private repo,** fork PR workflows don't run unless the repo turns them on, and GitHub doesn't offer the approval setting. So the fork rule hardly matters there. The rest of this section still applies.

**Everywhere:**

3. **The strongest option: a job-start hook on the runner.** Everything above lives in files or settings that someone else could change. A hook lives on your machine. Set `ACTIONS_RUNNER_HOOK_JOB_STARTED` in the runner's `.env` file to the path of a script. The runner runs it before every job, and if the script exits non-zero, the job fails at "Set up job" without running anything. The script can:
   - refuse any `GITHUB_ACTOR` that isn't on your allowlist (you, and your own Apps' `[bot]` accounts);
   - refuse a PR whose head repo, `.pull_request.head.repo.full_name` in `$GITHUB_EVENT_PATH`, isn't this repo.

   Then a fork PR that edits `runs-on` still can't use your runner. Keep the script and the allowlist where the runner's user can read them but not change them. When a new App or account starts running jobs, add it to the allowlist and re-run the refused job.
4. **Make the machine cheap to lose:**
   - run the runner as its own user, not yours, with no SSH keys, cloud credentials or browser profile;
   - better, use a VM or container, and start the runner with `--ephemeral` so each job gets a clean one;
   - keep no secrets on the machine beyond what the workflows are given.
5. **Turn off "Allow GitHub Actions to create and approve pull requests"** (Settings → Actions → General → Workflow permissions) when the repo has the agent App. With it on, a workflow's own token can approve a PR, which gets around the rule that a person approves. Spec-from-intent needs it only when there's no App.
6. **Remove a runner you no longer use.** A registered runner on a public repo is always a target.

Organizations on GitHub Team or Enterprise can also put the runner in a runner group and limit that group to chosen repositories and workflows.
