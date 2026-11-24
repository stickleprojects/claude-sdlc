# change.toml: what a change is, and whether it's done

Each change folder has a `change.toml` (#272):

```toml
number = "0058"
slug = "0058-working-lift"
title = "The working lift and stacked floors"
status = "done"
pr = "#282"
```

| Field | Comes from |
|---|---|
| `number`, `slug` | the folder name. They let a mislaid file be put back |
| `title` | the `# Intent:` or `# Bug:` heading |
| `status` | `open`; `done` once the change is built and merged (not deployed); `withdrawn` when its intent or bug has a `Withdrawn:` line |
| `pr` | optional: the PR that shipped it |

To list what isn't done: `make next REF=origin/main OPEN=1`, or `grep -l 'status = "open"' changes/*/change.toml`.

## Who keeps it in sync

| When | What happens | What holds it |
|---|---|---|
| A change starts | `make new-change` writes the file as `open` | |
| The heading changes | the intent skill runs `make sync-changes CHANGE=<slug> FIX=1` | `make validate` |
| The build PR | the build skill sets `done`, so merging makes it true | CI's `pr-title` check, on `build/<slug>` PRs with code |
| A withdrawal PR | adds the `Withdrawn:` line and sets `withdrawn` | `make validate` |
| A roadmap row changes | the row and the status must agree | `make validate` |
| The build PR is reverted | the revert takes the status back to `open` | |

On a build branch the file says `done` before its PR merges. `make next` without `REF` checks main before it believes that.

## The sweep: `make sync-changes`

Housekeeping, for when something got past the checks. It is also how a repo that had no `change.toml` files gets them.

```
git fetch origin
make sync-changes                                     # report
make sync-changes FIX=1                               # correct the working tree
make sync-changes CHANGE=0017 STATUS=done PR=12 FIX=1 # set one by hand
```

It compares with `origin/main`, never commits, and exits 1 while anything is left wrong. Review what it wrote and open a PR. It never turns `done` back to `open`, and leaves a reopened change open: it lists those as `decide`. It needs full history: in a shallow clone it won't guess a missing file's status.

## Limits

- CI finds a build PR by its branch name. A change shipped from another branch must be set by hand.
- A fix merged under another name looks open to git, so the sweep fills it in as `open`.
- A folder with no `change.toml` is allowed for now, and `make next` reads git history for it, as before.
