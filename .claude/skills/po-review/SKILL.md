---
name: po-review
description: Guide the product owner through an intent or spec PR. Explain each review finding in plain language, with the quoted text, collect their decisions, apply them to the artifact and reply on GitHub. Use when the product owner says "/po-review <PR#>", "walk me through PR N" or "review the spec PR".
---

# Product owner review of a PR

The product owner decides; you explain and do the typing. The decision is recorded on GitHub, where approving and merging the PR **is** the acceptance. Never approve or merge the PR yourself.

## 1. Load the PR

```
gh pr view <N> --json title,headRefName,body,files
gh pr diff <N>
gh pr view <N> --comments
gh api repos/{owner}/{repo}/pulls/<N>/comments
```

Work out the change folder (`changes/NNNN-name/`) and the stage: an `intent:` PR or a `spec:` PR. For any other kind of PR, say this skill isn't for it, and stop.

Check out the PR branch: `gh pr checkout <N>`.

## 2. Brief the product owner (one short message)

- What the change is, in one sentence taken from `intent.md`.
- What this PR asks them to accept: the intent or the spec.
- How many open items there are: unresolved review findings, plus anything under "Open questions".

## 3. Go through each item, one at a time

Skip findings that are already resolved: ones with a reply that says how they were handled, or ones the latest summary marks resolved. For each remaining item:

1. **Quote** the exact artifact text it refers to, such as the criterion or requirement, with its ID.
2. **Explain** the problem in plain language: what would go wrong, and when.
3. **Recommend** a fix, with the replacement wording.
4. **Ask** for a decision with AskUserQuestion: accept the recommendation, keep the text as it is (with a reason), or write their own wording.

Findings that belong to the engineer (plan or code) get noted and handed on, not decided here.

## 4. Apply and record

1. Edit only the artifact under review (`intent.md` or `spec.md`). Record each decision where the template expects it. For a spec, that's the "Product owner decisions" section.
2. Run `make validate`.
3. Commit with `<stage>: address review (product owner decisions)`, then `git push`.
4. Reply to each inline comment you handled with what was decided:
   `gh api repos/{owner}/{repo}/pulls/<N>/comments/<comment-id>/replies -f body="…"`

## 5. Hand back the gate

Tell the product owner:
- what changed, as a short list;
- that the push starts a fresh review, so they should check that its summary has no open findings;
- that they accept by merging the PR on GitHub once its checks are green (in team mode, a code owner approves first). You can't merge it for them: a hook blocks the agent from merging or approving.
