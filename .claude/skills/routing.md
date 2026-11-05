# Routing: where a change is, and who takes the next step

People remember five skills:

| Skill | For |
|---|---|
| `/intent` | something new: a feature, a request, or a bug |
| `/plan` | planning a change whose spec is merged |
| `/build` | building a change whose plan is merged |
| `/pr [N]` | working through the review on a PR: intent, bug, spec, plan or code |
| `/next [change]` | "where is everything, and what's next?" |

Every other skill (`spec`, `po-review`, `review-findings`, `agent-identity`, `security-policy`) is internal: hidden from the `/` menu, and reached only through these five. Each entry skill starts with the steps below. If the change isn't at its stage, it says where the change is and offers the right skill instead of failing or guessing.

## 1. Find out where each change is

```
git fetch --prune origin
make next REF=origin/main            # every change, from what's merged
make next REF=origin/main CHANGE=0002  # one change
```

Each line is `slug  stage  next-skill  detail`, for example `0002-breadcrumbs  plan  build  build it`. `done` means the build has merged. In a repo whose Makefile has no `next` target yet, run `make status` and use the table in step 3.

Then check what isn't on main yet:

- **Open PRs:** `gh api 'repos/{owner}/{repo}/pulls?state=open&per_page=100' --jq '.[] | "\(.number)\t\(.head.ref)\t\(.title)"'`. A PR belongs to a change when its branch or title carries the slug (`spec/0002-breadcrumbs`, `plan(0002-breadcrumbs): …`, `build/0002-breadcrumbs`).
- **A build under way:** a branch `origin/build/<slug>`. On it, `make next CHANGE=<slug>` (without `REF`) reads its build.md.
- **A merged build without build.md** (a small build): `gh api 'repos/{owner}/{repo}/pulls?state=closed&head={owner}:build/<slug>'` with `merged_at` set means it's done.

## 2. Pick the change

- **The person named one** (`0002` or `0002-breadcrumbs`): use it.
- **Otherwise:** the candidates are the changes whose next step is this skill's. One: use it, and say which. Several: ask which with AskUserQuestion, any already under way first. None: go to step 4.

## 3. The table

| On main | Open PR or branch | Next step | Skill |
|---|---|---|---|
| no change folder | | describe it | `/intent` |
| | intent or bug PR | the product owner works through its review | `/pr` |
| `intent.md` or `bug.md`, no spec | | the spec workflow opens a spec PR when it merges; if none appeared, write it (the internal `spec` skill) | `spec` |
| | spec PR | the product owner works through its review | `/pr` |
| `spec.md`, no plan | | plan it | `/plan` |
| | plan PR | the engineer works through its review | `/pr` |
| `plan.md` | maybe `build/<slug>` | build it (approve build.md first if it's a draft) | `/build` |
| | build PR | the engineer works through its review | `/pr` |
| build merged | | nothing: done | |

An open PR for the change's next artifact comes before the row for what's on main: if `plan(0002)` is open, the next step is its review, not another plan.

## 4. When the change isn't at this skill's stage

Say in one line where it is and what comes next, then ask with AskUserQuestion, recommendation first. For example, `/plan` on a change that's already planned:

> 0002-breadcrumbs is already planned (plan.md is merged). The next step is to build it.
> 1. Build it: I'll run /build for you (recommended)
> 2. Replace the plan: start planning again
> 3. Stop

- **On "go to the next step":** invoke that skill with the Skill tool, passing the slug, and follow it from its start. Don't ask the person to type it.
- **Never redo a finished stage silently.** Replacing a merged intent, spec or plan needs the person to choose it, and goes through a new PR like the first one.
- **Nothing for this skill at all** (for example `/build` with nothing planned): look one stage back and offer that. `/build` offers `/plan` when there's something to plan, which in turn offers the spec or the intent. When everything is done or waiting on someone else, say so, with what each change is waiting on, and stop.
- **Waiting on someone else** (a PR the product owner must review, a spec the workflow is still generating): say who, and link the PR. Don't offer to do their part.
