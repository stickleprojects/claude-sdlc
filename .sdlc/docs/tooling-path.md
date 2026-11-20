# The tooling path: what it skips, and what it can't

For engineering managers and tech leads deciding whether to turn it on.

## What it is

A change normally goes through four pull requests: the intent, its spec, a plan, and the code. That's the right cost for a feature, where the spec is where the product owner decides what users get. It's too much for a script, a CI job or a dev tool, which no user sees. One team's 170-line runner smoke test took 18 review rounds and 26 questions, most of them about spec-clause coverage (#221).

On the tooling path, a change goes through one PR, which holds:

- the intent (`intent.md`, with the line `Kind: tooling`);
- the plan (`plan.md`, whose base line is `Spec: none (tooling path)`), approved by the engineer in plan mode before any code is written;
- the code and its tests.

There's no spec. The intent's **Proposed outcome** statements are the acceptance checks, and the plan gives each one a Verification row: a test or command that would fail if it weren't met. Merging the PR accepts the intent, the plan and the code together.

## Turning it on

It's off until the repo's `CLAUDE.md` has a line listing the paths tooling may touch:

```
Tooling paths: scripts/ tools/ .github/
```

The entries are separated by spaces. An entry ending in `/` is a folder; any other entry is a file, or a folder of that name (`Makefile`). [settings.md](settings.md) lists it with the other settings.

## When a change may take it

`/sdlc-intent` offers the path, saying why in one line, when **all** of these hold:

- the repo has a `Tooling paths:` line;
- the change only adds or changes scripts, CI support or dev tools;
- every file of its code is inside those paths;
- it changes nothing about how the product behaves.

The person can ask for the full path instead. A change that is partly product code takes the full path. So does one that's unclear.

## What it doesn't skip

What changes is the number of PRs and the spec, not the checks. A tooling PR meets the same bar as any code PR:

| Check | Enforced by | What a developer can't do |
|---|---|---|
| Code stays inside the allowlist | CI's `pr-title` check (`check-plan-first.sh`), a required check. It reads `main`'s `CLAUDE.md`. | Touch a file outside `Tooling paths:`, or widen the list in the same PR. With no such line on `main`, a tooling change's code fails. |
| No code before the plan | The plan-gate hook, and the same CI check | Write code on `build/<slug>` before `plan.md` is committed there |
| The title says it's tooling | CI's `pr-title` check (`check-pr-title.sh`) | Title it anything but `chore(<slug>): …` or `ci(<slug>): …`, so it never shows up under Features or Bug fixes in the release notes |
| No spec | `make validate` | Add a `spec.md` to a tooling change; give a plan without a spec to a change that isn't tooling |
| An independent review | The `claude-review` required check | Merge while an Important thread is open. The review checks the code against the plan's Verification rows, and reports a change to product behaviour as Important. |
| Descopes need a person | The descopes check, as for every PR | Merge with an unapproved descope |
| A person merges | A hook stops Claude merging or approving; branch protection backs it up | Have the agent merge its own work |

## Where it still relies on judgement

1. **"Changes no product behaviour" is a judgement inside the allowlist.** A script under `scripts/` can still ship something users see: a migration, a data fix, a build step that changes the product. The review reports that as Important, but a person can resolve the thread and merge. Keep the allowlist to paths that really hold only tooling.
2. **The local hook doesn't check the allowlist.** The plan-gate hook lets code through on `build/<slug>` once the plan is committed. The required CI check is what holds the paths.
3. **The engineer accepts the intent.** No product owner signs off, because nothing a user sees changes. If your team wants a second person, run the repo in team mode, where every PR needs a code owner's approval.

## Tightening it

- **Turn it off:** remove the `Tooling paths:` line. Tooling changes then take the full path, and CI fails any change still marked `Kind: tooling` that brings code.
- **Narrow it:** list fewer paths, or files rather than folders.
- **Watch it:** tooling changes are the `chore(<slug>)` and `ci(<slug>)` PRs that bring in a `changes/<slug>/intent.md`. `make next` shows them as `built and merged`.
