# Running the pipeline on your own runner

The pipeline's workflows run on GitHub-hosted runners (`ubuntu-latest`). When those are down, every check stays queued and no PR can merge. To keep working, you can point every framework job at a runner of your own with one repository variable. Delete the variable afterwards to go back.

## Switch over

1. **Lock the repo down first** if it's public (see [Keep strangers off your runner](#keep-strangers-off-your-runner)).
2. **Register the runner** on the repo or its organization (Settings → Actions → Runners → New self-hosted runner). It gets the label `self-hosted`.
3. **Set the variable:**

   ```
   gh variable set SDLC_RUNNER --body self-hosted
   ```

   The value is one runner label. Queued runs don't move: re-run them (`gh run rerun <id>`), or push a commit.
4. **When GitHub's runners are back:** `gh variable delete SDLC_RUNNER`.

Each job asks for:

```yaml
runs-on: ${{ vars.SDLC_RUNNER && (github.event.pull_request.head.repo.full_name || github.repository) == github.repository && vars.SDLC_RUNNER || 'ubuntu-latest' }}
```

In words: use `SDLC_RUNNER` when it's set, unless the run is for a PR from a fork. Fork PRs always go to GitHub-hosted runners.

## What the runner needs

- Linux with `bash`, `git`, `make`, `curl` and `jq`
- the `gh` CLI (the review and merge scripts call it)
- nothing for the JavaScript actions: the runner brings its own Node for those, and `claude-code-action` installs the tools it uses
- whatever `.github/actions/setup-stack/` doesn't install itself. Here that's nothing beyond the above, since it installs `uv`. A consumer whose stack uses other tools (Bun, say) needs them on the runner or installed by its setup steps.

## Keep strangers off your runner

On a public repo, anyone can open a PR from a fork, and a PR's workflows run from the PR's own copy of the workflow files. The fork rule in `runs-on` only holds if nobody edits it: a fork PR can change `runs-on` to `self-hosted` and run anything on your machine. These settings are what keep it out:

1. **Approve every fork PR's workflows yourself.** Settings → Actions → General → *Approval for running fork pull request workflows from contributors* → **Require approval for all external contributors**. From the command line:

   ```
   gh api -X PUT repos/<owner>/<repo>/actions/permissions/fork-pr-contributor-approval \
     -f approval_policy=all_external_contributors
   ```

   Then no fork PR's workflow runs anywhere until a maintainer clicks *Approve and run workflows*. Read the PR's workflow changes before you click. The sync warns when `SDLC_RUNNER` is set on a public repo without this setting.
2. **Only people you trust have write access.** Collaborators can push branches to the repo itself, and those runs don't ask for approval.
3. **Make the machine cheap to lose:**
   - run the runner as its own user, not yours, with no SSH keys, cloud credentials or browser profile on it;
   - better, use a VM or container, and start it with `--ephemeral` so each job gets a clean runner;
   - don't keep secrets on the machine beyond what the workflows are given.
4. **Remove the runner when the outage is over** (Settings → Actions → Runners), as well as the variable. A registered runner on a public repo is a standing target.

Organizations on GitHub Team or Enterprise can also put the runner in a runner group and limit that group to chosen repositories and workflows.

On a private repo, fork PR workflows don't run unless the repo allows them, so steps 1 and 2 matter less. Step 3 still applies.
