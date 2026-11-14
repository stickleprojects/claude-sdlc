You check one requirement of a spec for clause coverage (issue #47). Don't use any tools,
and don't read any files: everything you need is in the block below.

The block is JSON: the requirement's `text`, the acceptance `criteria` that cite it, and the
`plan` lines that cite it or its criteria (each with the plan section it sits in).

1. Split the whole requirement's text into clauses, start to end, before judging any of them:
   every uncovered clause has to be in this one answer, because a gap found later costs another
   review round (#160). A clause is one separate outcome that could be tested on its own:
   each thing it "shows", "has", "is" or "combines with", each "otherwise"
   or fallback, and each "when … then" rule. A list of items the requirement names (fields,
   columns, places it appears) is one clause per item when each item could be missing on its own.
   Don't split a clause only because of a modifier ("quickly", "clearly").
2. For each clause, decide whether it is covered:
   - **Stage `spec`:** at least one criterion tests that clause, or an `Untestable` entry names
     it with a reason.
   - **Stage `plan`:** as for `spec`, and the plan also has a design line for it (any section
     other than Verification) and a Verification row that would fail if the clause weren't met.
   Judge by what the criterion or plan line actually checks, not by whether it cites the
   requirement's ID. A criterion that cites the requirement but tests only some of its clauses
   covers only those.
3. Report every clause that isn't covered, not only the first one you find. Quote each clause in the requirement's own
   words (a short exact extract), and say what's missing: `criterion`, `design` or
   `verification` (a list, since a clause can lack more than one).

End your answer with exactly one line that starts with `CLAUSES: ` followed by a JSON array on
the same line, and nothing after it, for example
`CLAUSES: [{"clause": "with a way to clear the search", "missing": ["criterion"]}]`
(without the backticks). Write `CLAUSES: []` when every clause is covered.
