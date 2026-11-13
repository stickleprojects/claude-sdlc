# Routing: where a change is, and who takes the next step

People remember six skills:

| Skill | For |
|---|---|
| `/sdlc-intent` | something new: a feature, a request, or a bug |
| `/sdlc-plan` | planning a change whose spec is merged |
| `/sdlc-build` | building a change whose plan is merged |
| `/sdlc-pr [N]` | working through the review on a PR: intent, bug, spec, plan or code |
| `/sdlc-next [change]` | "where is everything, and what's next?" |
| `/sdlc` | the pipeline itself: which version, what's new, update it (sync PR) |

Every other skill (`sdlc-spec`, `sdlc-po-review`, `sdlc-review-findings`, `sdlc-agent-identity`, `sdlc-security-policy`) is internal: hidden from the `/` menu, and reached only through these six. Each entry skill except `/sdlc` (which is about the framework, not a change) starts with the steps below. If the change isn't at its stage, it says where the change is and offers the right skill instead of failing or guessing.

## 1. Find out where each change is

```
git fetch --prune origin
make next REF=origin/main            # every change, from what's merged
make next REF=origin/main CHANGE=0002  # one change
```

Each line is `slug  stage  next-skill  detail`, for example `0002-breadcrumbs  plan  sdlc-build  build it`. `done` means the build has merged; `withdrawn` means it was binned (the detail says who, when and why). A detail starting `out of date:` means an earlier artifact changed after a later one, so the change has gone back a step (see [Going back](#going-back-and-pushback)). In a repo whose Makefile has no `next` target yet, run `make status` and use the table in step 3.

Then check what isn't on main yet:

- **Open PRs:** `gh api 'repos/{owner}/{repo}/pulls?state=open&per_page=100' --jq '.[] | "\(.number)\t\(.head.ref)\t\(.title)"'`. A PR belongs to a change when its branch or title carries the slug (`spec/0002-breadcrumbs`, `plan(0002-breadcrumbs): …`, `build/0002-breadcrumbs`).
- **A build under way:** a branch `origin/build/<slug>`. On it, `make next CHANGE=<slug>` (without `REF`) reads its build.md.
- **A merged fast-path bug** (bug.md and spec.md, no plan.md): `make next` shows it `done` when the PR that merged from `build/<slug>` (or the squashed `fix(<slug>): … (#N)`) brought its `spec.md` with it (#148). A bug report merged on its own never counts.
- **A merged build without build.md** (a small build): `make next` reads it from main's history, as the merge commit `Merge pull request #N from <owner>/build/<slug>`, or the squashed PR title `feat(<slug>): … (#N)`, and shows it `done` (#122). In a repo that rebase-merges neither exists. There, `gh api 'repos/{owner}/{repo}/pulls?state=closed&head={owner}:build/<slug>'` with `merged_at` set means it's done.

## 2. Pick the change

- **The person named one** (`0002` or `0002-breadcrumbs`): use it.
- **Otherwise:** the candidates are the changes whose next step is this skill's. One: use it, and say which. Several: ask which with AskUserQuestion, any already under way first. None: go to step 4.

## 3. The table

| On main | Open PR or branch | Next step | Skill |
|---|---|---|---|
| no change folder | | describe it | `/sdlc-intent` |
| | intent or bug PR | the product owner works through its review | `/sdlc-pr` |
| `intent.md` or `bug.md`, no spec | | the spec workflow opens a spec PR when it merges; if none appeared, write it (the internal `sdlc-spec` skill) | `sdlc-spec` |
| | spec PR | the product owner works through its review | `/sdlc-pr` |
| `bug.md` and `spec.md` on `build/<slug>`, nothing on main | | a bug on the fast path: finish the fix, then the PR | `/sdlc-build` |
| | fast-path `fix(<slug>)` PR | both walkthroughs: the product owner for the bug and spec, then the engineer for the code | `/sdlc-pr` |
| `spec.md`, no plan | | plan it | `/sdlc-plan` |
| | plan PR | the engineer works through its review | `/sdlc-pr` |
| `plan.md` | maybe `build/<slug>` | build it (approve build.md first if it's a draft) | `/sdlc-build` |
| | build PR | the engineer works through its review | `/sdlc-pr` |
| build merged | | nothing: done | |
| `Withdrawn:` line | | nothing: binned | |
| an artifact `out of date:` | | update it, or confirm it still holds | its owner: `sdlc-spec`, `/sdlc-plan` or `/sdlc-build` |

An open PR for the change's next artifact comes before the row for what's on main: if `plan(0002)` is open, the next step is its review, not another plan.

## 4. When the change isn't at this skill's stage

Say in one line where it is and what comes next, then ask with AskUserQuestion, recommendation first. For example, `/sdlc-plan` on a change that's already planned:

> 0002-breadcrumbs is already planned (plan.md is merged). The next step is to build it.
> 1. Build it: I'll run /sdlc-build for you (recommended)
> 2. Amend the plan: change part of it through a new plan PR
> 3. Replace the plan: start planning again
> 4. Stop

- **On "go to the next step":** invoke that skill with the Skill tool, passing the slug, and follow it from its start. Don't ask the person to type it.
- **Never redo a finished stage silently.** Replacing a merged intent, spec or plan needs the person to choose it, and goes through a new PR like the first one.
- **Nothing for this skill at all** (for example `/sdlc-build` with nothing planned): look one stage back and offer that. `/sdlc-build` offers `/sdlc-plan` when there's something to plan, which in turn offers the spec or the intent. When everything is done or waiting on someone else, say so, with what each change is waiting on, and stop.
- **Waiting on someone else** (a PR the product owner must review, a spec the workflow is still generating): say who, and link the PR. Don't offer to do their part.

## Going back and pushback

A change's column is worked out from git, so going back a column means **amending an earlier artifact** through its own PR, never setting a status. Once the amendment merges, everything after it is out of date, and `make next` sends the change back to it.

- **Out of date:** an artifact whose base (spec after intent or bug, plan after spec, an unfinished build after plan or spec) changed after it was last committed. Its owner either updates it, or confirms it still holds by re-committing it with its base line noting the check, e.g. `Spec: ./spec.md (checked against abc1234, no change)`. A typo fix upstream doesn't force rework. A merged build stays done whatever changes later: what's shipped stays shipped.
- **Amend:** offered by an entry skill run on a change past its stage. Amending an intent or spec is the product owner's decision (offer it, and route it to them through `/sdlc-pr` on the amendment PR); amending a plan is the engineer's.
- **Withdraw (bin it):** add `Withdrawn: <who>, <date>: <why>` to the intent.md or bug.md, in a PR like any other change to it. Close the change's open PRs with that reason. Keep the build branch, so the work can be recovered. Only someone who can accept the intent (the product owner) decides it.

**Where pushback goes.** The aim is to build and deploy fast enough that work rarely sits in dev long enough to be pushed back, so most pushback should arrive as bugs:

| Pushback | Becomes |
|---|---|
| QA or review before merge: the code is wrong | findings on the build PR (`/sdlc-pr`), or a `reopened` milestone in build.md |
| The plan is wrong (found building or testing) | amend the plan (`/sdlc-plan`); build.md goes back to draft for approval |
| The spec or intent is wrong | amend it (product owner); the plan and the build go out of date |
| Bin it | withdraw it |
| **Anything found after merge or release** | **a new bug change** (`/sdlc-intent`, which takes the bug path), with `Came from:` naming the change it was found in. Never reopen a merged change |
