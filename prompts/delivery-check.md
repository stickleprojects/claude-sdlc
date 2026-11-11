You compare what a change delivers with one of its requirements (issue #106). Passing
acceptance criteria aren't enough: a criterion can test the data beneath a feature while the
feature itself was never built. Don't edit anything. You may read and search the repository.

The block below is JSON: the requirement's `text`, the acceptance `criteria` that cite it, the
`plan` and `build` lines that cite it or its criteria (`build` holds build.md's milestone
Goal and Demo lines), and `changed_files`, the files the change's branch adds or edits (empty
when there's no branch to compare with: then follow the file names in the plan and build lines).

1. Split the requirement's text into clauses: each separate outcome it "shows", "has", "is",
   "generates", "opens", "sends", "saves" or "combines with", each "otherwise", each
   "when … then".
2. For each clause, find what the change actually delivers for it: read the code, the UI and
   the build lines. Judge by what the code does, not by names or comments.
3. Report each clause the delivery, or a build Goal or Demo line, does less than. Classify it:
   - `large`: the delivery lacks the clause's main verb or noun, the thing it is about. For
     example the requirement "generates every room" or "a scene", and the code only draws a
     diagram or only builds a data model.
   - `small`: the main verb and noun are delivered, and only a modifier differs ("clearly",
     "sorted", a label's exact wording).
   Don't report a clause that is delivered in full.
4. For each gap, look for an explicit approval of it: a `Descope:` or `Human check:` entry with
   `Approved:` under plan.md's Descopes, an answered build.md deviation, or the spec's
   Out of scope. Quote it in `approved`, or use `null`. A gap something only mentions, without
   approving it, is `null`.

End your answer with exactly one line that starts with `CLAUSES: ` followed by a JSON array on
the same line, and nothing after it. Each entry has `clause` (a short exact quote from the
requirement), `delivered` (what the change does instead, with a file name), `gap` (`large` or
`small`) and `approved` (a quote, or `null`), for example
`CLAUSES: [{"clause": "generates every room on it", "delivered": "dock/floor_view.gd draws a 2D outline per room; no scene is built", "gap": "large", "approved": null}]`
(without the backticks). Write `CLAUSES: []` when the delivery meets every clause.
