# The bug fast path: what it skips, and what it can't

For engineering managers and tech leads deciding whether to allow it.

## What it is

A bug normally goes through four pull requests: the bug report, its spec, a plan, and the fix. Each one waits for a review and a merge. On the fast path, a small bug goes through one PR, which holds all of these:

- the bug report (`bug.md`);
- a short spec: what correct behaviour is, and one acceptance test per symptom;
- tests that fail on the current code, committed before the fix;
- the fix.

Approving that PR means "fix this, this way", not just "yes, that's a bug". No plan is written, because there's nothing to design: the cause is known and the fix stays inside the code that has it.

It exists because the full path cost one team a working day for a 40-minute fix: 4 PRs and about 13 review runs (#160).

## When a bug may take it

Claude proposes the path when the bug is reported (`/sdlc-intent`), and says why in one line. The person can ask for the full path instead. A bug takes the fast path only when **all** of these hold:

- what should happen is clear, and no product decision is open;
- the cause has been found, and the fix stays inside the code that has it;
- it needs no new dependency or service, nothing the security policy covers, no architecture decision, and no migration of data that users or installs already hold;
- the fix, its tests and the PR fit in one working session.

How many files it touches doesn't count against it. Uncertainty, risk and design do. Anything else takes the full path.

## What it doesn't skip

What changes is the number of PRs, not the checks. The fast-path PR meets the same bar as any code PR, and some of that bar is enforced by machines, not left to the developer:

| Check | Enforced by | What a developer can't do |
|---|---|---|
| No code before the spec | A local hook, and CI's `pr-title` check (`check-plan-first.sh`), which is a required check | Open a code PR for a change that has neither a plan nor a committed bug report and spec. The exception holds only on the change's own `build/<slug>` branch. |
| The PR's title shows it's a bug fix | CI's `pr-title` check (`check-pr-title.sh`) | Give the PR any title other than `fix(<slug>): …`, or add files that belong to a different change. Because of the title, the fix is listed under **Bug fixes** in the release notes. |
| An independent review | The `claude-review` required check, run on the PR by an agent that didn't write it | Merge while an Important finding's thread is unresolved. The review checks the bug and spec for completeness, and the code against every acceptance criterion. It reports a bug too big for the fast path as Important. |
| Failing tests first | A local hook locks the test files once the `test(<slug>): …` commit is made. The verifier and the review check that commit comes before the fix. | Edit the failing tests to make them pass, in a Claude session. |
| A person merges | A hook stops Claude merging or approving. Branch protection (`enforce_admins`) applies to admins too. | Have the agent merge its own work. |
| Team mode: an approval | Branch protection: one approval from a code owner | Merge without someone else's approval. |

## Where it still relies on judgement

Be clear about these before you turn it on:

1. **"Small" is a judgement call.** Claude proposes the path, and the review challenges it. But a person can resolve the review's "too big" thread and merge anyway. That person's approval is the control, as it is for any PR.
2. **The product owner's approval isn't required by GitHub yet.** In team mode the one required approval can come from an engineer, even though the PR also holds product content (the bug and spec). The review's summary says the bug and spec need the product owner's sign-off, and `/sdlc-pr` runs both walkthroughs. You can make GitHub require both today by editing CODEOWNERS (see [Tightening it](#tightening-it)). #151 will set that up for you.
3. **CI doesn't prove the tests failed before the fix.** It runs the tests at the PR's head, where they pass. That they failed first is checked from the commit order by the verifier and the review, which are AI checks, not a test run on the old code.
4. **A PR outside the pipeline isn't checked by CI.** The plan check looks only at a change's own branches (`build/<slug>` and the like). A developer who fixes something on a branch such as `fix/typo`, with no bug report at all, gets past it. The review catches this: a PR that changes how the product behaves without a change folder is an Important finding, so it can't merge until a person resolves that thread. This was true before the fast path, and the fast path doesn't change it.
5. **Solo mode needs no approval at all.** That's true of every PR in solo mode, not just this one.

## Tightening it

- **Turn it off:** add the line `Bug path: full` to the repo's `CLAUDE.md` (`settings.md`). Claude stops offering the fast path, and CI's `pr-title` check fails a bug's PR that brings code without a plan. CI reads the line from `main`, so a PR can't remove it to get its own fix through.
- **Require an approval on every PR:** run the repo in team mode (`bootstrap-github.sh --mode team`). Each PR then needs one approval from someone listed in `.github/CODEOWNERS`, other than its author.
- **Require the product owner's approval as well, on a fast-path PR:** in `.github/CODEOWNERS`, make the product owner the owner of `changes/*/bug.md` and `changes/*/spec.md`, and the engineers the owners of everything else. In team mode, GitHub then won't merge the PR until both have approved (#151).
- **Watch it:** fast-path fixes are the `fix(<slug>): …` PRs that bring in a `changes/<slug>/spec.md`. `make next` lists them as "fixed on the fast path and merged", and the release notes list them under Bug fixes.
