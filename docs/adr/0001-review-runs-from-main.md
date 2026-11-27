# ADR 0001: The AI review runs from main's copy of its workflow, and a person approves CI changes

## Status

proposed

## Context

`sdlc-claude-review.yml` runs on `pull_request`, so GitHub runs the PR's copy of the workflow (#293). That has two effects.

1. **A PR that changes a review workflow gets no AI review of any file.** claude-code-action swaps the job's OIDC token for its App's token, and the swap refuses when the running workflow file differs from the default branch's (`src/github/token.ts`). Our *Note when the AI review can't run* step then skips the review, and a code owner reviews the PR by hand. A consumer's sync PR is about 900 files, and 12 of the last 18 releases changed a claude workflow. So two sync PRs in three got no AI review. The sync PR after #303 and #304 will be another.
2. **A PR can change how its own review runs.** The rules (`.sdlc/REVIEW.md` through `resolve.sh`) and the thread scripts are read from the base, but the steps, the prompt and the tool allowlist come from the PR.

What constrains the choice:
- **The token swap passes only when the running workflow matches main's.** Under `pull_request_target`, GitHub runs main's copy.
- **claude-code-action reads a `pull_request_target` event the way it reads `pull_request`.** The pinned v1 handles both in the same `case` of `src/github/context.ts`.
- **A privileged run must never run PR code.** Under `pull_request_target` or `workflow_run`, the job has main's secrets and a token that can write. Today the review job runs three things from the PR's checkout:
  - the local `./.github/actions/setup-stack`;
  - `make clauses`;
  - `make -n clauses`, which can run `$(shell …)` while it parses the PR's Makefile.
- **Forks get secrets under `pull_request_target`.** The fork guard (`head.repo.full_name == github.repository`) must hold before any step. checkout v7 also refuses a fork PR's code under this event unless the step opts in.
- **`sdlc-check-after-review.yml` is triggered by the review's `workflow_run`.** It takes the PR's head from `workflow_run.head_sha`. For a `pull_request_target` run, that's main's head, not the PR's.
- **Kieron's direction (27 Nov):**
  - redesign the review, rather than pass our own token, since "plugging the gap seems more secure";
  - files that control CI get a person's approval and are pointed out, but the rest of the PR is still reviewed.

## Decision

- **The review moves to `pull_request_target`, with the same event types as today.** GitHub runs main's copy, so a PR can't turn its review off or change how it runs.
- **The job checks out main at the workspace root:** its scripts, `REVIEW.md` and `setup-stack`.
- **The PR's head is checked out into `pr/` as data only.** It gets no credentials, isn't on `PATH`, and nothing in it is sourced or run with `make`.
- **The clause check runs main's tool over the PR's spec and plan files as input.** It doesn't run the PR's Makefile.
- **The review covers every file.** A PR that changes a file that sets the safety rules also gets one `CI change: needs approval` thread, listing those files.
  - The files (Kieron, 27 Nov):
    - everything under `.github/`: workflows, actions, `dependabot.yml`, `CODEOWNERS`;
    - `.sdlc/hooks/**`, the agent's guardrails;
    - `.claude/settings.json`, which wires those hooks in;
    - the lockfiles, `uv.lock` and `.github/workflows/actions.lock`.
  - They decide what runs in CI, with what permissions, who approves, and what the agent may do, so a change to any of them changes the rules, not the product.
  - The `Makefile` and `.sdlc/scripts/` aren't on the list:
    - the `Makefile` is the stack contract, changed routinely, and in CI it runs only with a read-only token;
    - most PRs touch `.sdlc/scripts/`, so a thread on every PR would teach people to approve without reading.
    
    The normal review covers both.
  - `descopes-decided.sh` holds the thread like a descope: `claude-review` fails until a person replies `Approved: <name>, <date>`.
  - The AI review of these files is advice, never the only check.
- **The fork guard moves to the job's `if`,** so a fork's PR runs no step.
- **Dependabot PRs still get no AI review** (#303).
- **The run carries its PR number in a `run-name`,** e.g. `Claude review #123`. The after-review gate reads the number from `workflow_run.display_title` and then takes the PR's current head from the API, as it already does for *Descope decisions* (#223). It also accepts `workflow_run.event == 'pull_request_target'`.

## Alternatives considered

- **Pass our own `github_token`, so the App's check is skipped.** It gets the review running, but the PR still controls its own review (effect 2). Kieron rejected it on 27 Nov.
- **A `workflow_run` review after an unprivileged `pull_request` workflow.** This is how `sdlc-check-after-review.yml` works.
  - It costs a second workflow and a second run per PR.
  - claude-code-action treats `workflow_run` as an automation event, not a PR, so it would need its agent mode and a hand-built prompt and context.
  - `pull_request_target` gets the same privilege boundary with one workflow and the action's normal PR handling.
- **Keep `pull_request` and skip the review on any CI change (today).** Two sync PRs in three get no AI review of their other files, and effect 2 stays.
- **Approval for every file in a workflow-changing PR.** It's the same as today's skip, with a different label: the person reviews 900 files by hand.

## Consequences

- **Every PR gets an AI review, the sync PR included.** A person approves only the CI files, in one thread.
- **What a PR can change:** the PR's copy of the review workflow no longer affects its own review. A change to the review takes effect only once it's on main. So a PR that changes the review is reviewed by the old review, and the person approving it has to read the workflow change.
- **Rules for the privileged job, which need a test** like `test_stack_contract.py`. It fails on any of these:
  - a `uses: ./…` from `pr/`;
  - a `make` or script run from `pr/`;
  - a checkout of the PR without `path: pr` and `persist-credentials: false`;
  - a missing fork guard on the job.
- **The review prompt reads files under `pr/`.** The prompt changes, so an eval covers it.
- **Consumers:**
  - The workflow is framework-owned, so every consumer gets the change through the sync. That sync PR is the last one that skips its AI review.
  - No repo setting changes, but behaviour does: `claude-review` now fails on a CI change until someone approves it. So the PR title takes a `!`.
  - The release notes say so.
- **The mention workflow stays as it is.** Its job is to run the PR's code and commit to it, so it can't be data-only. It answers only to `issue_comment`, which already runs main's copy, and to `pull_request_review_comment`, which runs the PR's. Its exposure is a separate question: #306.
- **Almost every consumer sync PR gets the approval thread,** since a sync usually changes a workflow or a hook. That's one thread to read, in place of 900 unreviewed files.
- **What we maintain:**
  - the `pr/` layout;
  - the `run-name` contract between the review and the gate;
  - one more thread type in `descopes-decided.sh`.

## Revisit when

- a plan makes the review job run a command, `make` target or action from the PR's checkout
- a plan widens the review's tool allowlist to anything that writes files or runs commands
- claude-code-action stops handling `pull_request_target` as a PR event, or its token swap accepts a PR's copy of the workflow
- a plan adds a file outside the approval list that sets what CI runs with secrets, or what the agent may do (it joins the list)
- people approve `CI change: needs approval` threads without reading them, e.g. because the list now matches most PRs
- the after-review gate needs the reviewed head and can't get it from the PR number
