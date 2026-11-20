# What each job needs from setup-stack

For whoever maintains a project's `.github/actions/setup-stack/`.

Every synced workflow calls your `setup-stack` action. If installing your stack is slow (a game engine, a large toolchain, a fresh runner for every job), you don't have to install all of it for every job. Each call tells the action what that job needs, in the environment variable `SDLC_STACK_NEEDS` (#239). An action that ignores the variable installs everything, as before, so nothing changes until you choose to read it.

## The levels

Each level includes everything in the levels above it.

| `SDLC_STACK_NEEDS` | The job needs | Jobs |
|---|---|---|
| `none` | nothing from your stack: only what the runner has (git, bash, python3) | (none yet) |
| `validate` | the pipeline's own make targets, `make validate` and `make clauses`, as your `$(SDLC)` runs them. With the default `SDLC`, that's stdlib Python, so nothing more. | `sdlc-claude-review.yml` / `review` |
| `commit` | `validate`, plus whatever an agent needs to make a commit your hooks accept: the formatter `make fmt` runs, git hooks, a secret scan | `sdlc-claude-mention.yml` / `respond`, `sdlc-spec-from-intent.yml` / `spec` |
| `full` | everything `make check` needs | `sdlc-ci.yml` / `check`, `sdlc-check-after-review.yml` / `make-check`, `sdlc-agent-evals.yml` / `evals` |
| unset, or anything else | treat it as `full` | |

The value is a contract, not a guess from the job's name. A sync that renames a workflow or a job keeps the value, so the saving doesn't silently disappear.

## Reading it

In a composite action, each step sees the variable in its environment:

```yaml
runs:
  using: composite
  steps:
    - shell: bash
      run: |
        case "${SDLC_STACK_NEEDS:-full}" in
          none | validate) echo "nothing to install" ;;
          commit) make setup-lint ;;   # the formatter, hooks and secret scan
          *) make setup ;;             # full, unset or unknown: everything
        esac
```

Treat a value you don't recognise as `full`. A later release may add a level, and installing too much is slow but correct, while installing too little fails the job.
