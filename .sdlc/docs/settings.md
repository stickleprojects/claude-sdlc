# Settings

The pipeline's defaults suit a small team. A project changes them in one of three places, depending on what reads the setting:

- **A line in the repo's `CLAUDE.md`:** the skills read these, so they change how Claude works in a session. Add the line anywhere in the file.
- **A repository variable** (`gh variable set <NAME> --body <value>`): the workflows read these, so they change what CI does.
- **An environment variable** in the session: the hooks read these.

A setting that isn't there takes its default.

## In CLAUDE.md

| Line | Values | Default | What it changes |
|---|---|---|---|
| `Bug path:` | `fast`, `full` | `fast` | `fast`: `/sdlc-intent` puts a small bug with a known cause into one PR, holding its report, short spec, failing tests and fix, so approving it ships the fix (#148, #160). A bug that needs a product decision, a design decision, a new dependency or a data migration still takes the full path ([bug-fast-path.md](bug-fast-path.md) says what it skips and what it can't). `full`: every bug goes through a bug PR, a spec PR, a plan and a build, and CI's `pr-title` check fails a bug fix with no plan. CI reads the line from `main`'s CLAUDE.md. |
| `Change tracking:` | `issues` | change folders | `issues`: changes are tracked as GitHub issues, not `changes/` folders, and the review stops asking for a change folder. The framework repo uses it. |

## Repository variables

| Variable | Values | Default | What it changes |
|---|---|---|---|
| `SDLC_AUTO_MERGE` | `merge`, `squash`, `rebase`, `off` | off | Turns on GitHub's auto-merge for the PRs the pipeline opens, and re-reviews each push (team mode only; see the readme). |
| `SDLC_REVIEW_EXTRA_BOTS` | bot names, comma-separated | none | Bots whose PRs the Claude review accepts, such as `renovate` (see the readme). |
| `SDLC_RUNNER` | a runner label | `ubuntu-latest` | Runs every framework job on your own runner (`self-hosted-runner.md`). |
| `SDLC_AGENT_APP_ID`, `SDLC_AGENT_APP_SLUG` | the App's id and slug | none | The GitHub App Claude acts as (`setup-agent-apps.md`). |

## Environment variables

| Variable | Values | Default | What it changes |
|---|---|---|---|
| `SDLC_PLAN_GATE` | `0` | on | `0` turns off the hook that blocks code before `plan.md` is committed. CI still checks it. |
| `SDLC_LOCK_TESTS` | `1` | off | `1` locks every test file, not only a bug fix's failing test. |
