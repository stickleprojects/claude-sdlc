# The roadmap

A roadmap is optional. A project that has `docs/roadmap.md` gets an ordered list of milestones that the pipeline reads and checks: `/intent` places each new change on it, `/build` marks the change done, `/next` shows what's left, and `make validate` fails when the roadmap, the intents and the adjustment records disagree. A project without one sees none of this.

The format came from spellbound3d, which used it for a dozen changes before the framework took it on (#81).

## Starting one

Copy `templates/roadmap.md` to `docs/roadmap.md` and fill in the first milestone. The file is the project's own: the sync never touches it. From the next `make validate`, every change folder that has an `intent.md` needs a row and a `Milestone:` line, so a repo with changes already in it adds those in the same PR. Bug changes (`bug.md`) are never on the roadmap.

## Milestones

```
## M2: Phone access · `in progress`

**Goal:** what is true once it's done, and why it comes here in the order.

**Scope**
- What it includes. Cite its sources, and the adjustment records that moved it.

**Exit criteria**
- [ ] A testable statement.
- [x] One that's met, with how.

### Changes

| Change | Summary | Status |
|---|---|---|
| [0004-phone-access](../changes/0004-phone-access/) | Read the app on a phone | planned |
| [0003-breadcrumbs](../changes/0003-breadcrumbs/) | The breadcrumb trail | ✅ done |
```

- **Heading:** `## M<n>: <name> · `<status>``. The status is `draft` (not agreed yet), `agreed`, `in progress` or `done`. A done milestone's heading ends ``· ✅ `done` ``. The green tick goes on done milestones and done rows, and nowhere else.
- **Exit criteria:** checkboxes under `**Exit criteria**`. A `draft` milestone may have none yet; any other needs at least one. A `done` milestone has every box ticked.
- **Changes:** one `### Changes` table per milestone, one row per change, with the change linked as `[NNNN-slug](../changes/NNNN-slug/)`. A row is `planned`, `✅ done` or `withdrawn`. A `done` milestone has only done and withdrawn rows.
- **Other sections**, such as *Later, not yet ordered*, are any `##` heading that isn't `M<n>:`. They aren't checked.
- **The order is the product owner's.** The pipeline reads it and never reorders it.

## Who writes what

| When | What changes |
|---|---|
| The intent PR (`/intent`) | The intent gets `Milestone: M<n>`. The milestone's table gets the change's row as `planned`. Any adjustment record is added. |
| The build PR (`/build`) | The row becomes `✅ done`. If that finishes the milestone, the person decides whether to mark the milestone done and tick its exit criteria. |
| Withdrawing a change | The intent gets its `Withdrawn:` line and the row becomes `withdrawn`, in the same PR. |

The check compares each row with the change's state as `make next` reads it:

- a withdrawn intent must be `withdrawn`;
- a large build whose build.md says `PR open` must be `✅ done`;
- a small build whose PR has merged (found in the git history, as `make next` finds it) must be `✅ done`, and one that hasn't may be either, because the check can't always read the history (a shallow clone, a repo that rebase-merges);
- on the change's own build branch (`build/<slug>`), the row may be `✅ done` before it merges;
- anything else must be `planned`.

## Adjustment records

A change that doesn't fit its milestone's agreed scope gets a record, and so does any move in a milestone's goal, exit criteria or order, or a new milestone. It's how scope moves out of a milestone too: a descope from a milestone is an adjustment.

- **One file per record:** `docs/roadmap/adjustments/NNNN-<slug>.md`, from `templates/roadmap-adjustment.md`. Records are numbered in their own series, separate from change numbers.
- **Fields:** `Status: proposed | accepted | superseded`, `Milestones: M1, M2`, `Changes: scope | goal | exit criteria | order | new milestone`, `Intent:` (a link to the change folder), an optional `Supersedes: NNNN`, and `## What changes` and `## Why` sections.
- **Written in the intent PR** of the change that needs it, as `accepted`: merging that PR is the acceptance. The intent names it in an `Adjustment: NNNN-<slug>` line, and the milestone's scope text cites it.
- **Never edited away.** A new record supersedes an old one, and the old one is marked `superseded`.

## The intent PR's Roadmap section

The intent PR body names the milestone (by name, not only by number, because numbers change when the roadmap is reordered), says whether the change delivers the whole milestone or part of it, lists what it knowingly leaves out, and names any adjustment record. The product owner sees what's left out before approving.
