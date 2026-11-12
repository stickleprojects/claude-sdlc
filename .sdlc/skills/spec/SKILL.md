<!-- The frontmatter for this skill is in .claude/skills/spec/SKILL.md, which Claude Code reads. Projects change this
file with an override in .sdlc-local/ (see .sdlc/docs/overrides.md), never by editing it. -->

# Write a spec from an intent

Input: a change folder, `changes/<slug>/`, that contains an accepted `intent.md`, or `bug.md` for a bug. For a bug, follow [For a bug](#for-a-bug) instead of the steps below.

1. Read `intent.md`, `CLAUDE.md` and the code the intent touches.
2. Copy `.sdlc/templates/spec.md` to `changes/<slug>/spec.md` and fill in every section:
   - **Requirements:** numbered (R1, R2, …). Each one is testable on its own.
   - **Acceptance criteria:** quantifiable checks, e.g. "`make check` exits 0" or "command prints X". Write each as a bullet `- AC<n> (R<n>, …): …`, never a numbered list (`1.`): the coverage checks read only that form, and `make validate` fails a spec without it. Each criterion is tested at the level it describes (`.sdlc/skills/scope.md`): say "through the UI" or "inside the editor" when that's what it means.
   - **Clause coverage:** a criterion can cite a requirement and still test only part of it (#47). Split each requirement into clauses, one per separate outcome: each thing it "shows", "has", "is" or "combines with", each "otherwise" or fallback, each "when … then". Every clause needs at least one criterion that tests it. If a clause truly can't be tested, add `- Untestable (R<n>): "<clause>" because <reason>.` under Acceptance criteria, and list it for the product owner. `make clauses CHANGE=<slug>` prints each requirement with the criteria that cite it, to check against.
   - **Policy concerns:** apply every policy skill in `.claude/skills/` (e.g. `security-policy`). Flag anything the intent asks for that a policy restricts, and any case where two policies contradict each other. Write "None" only if you checked and found nothing.
3. **Requirements that rely on people writing text in a set format.** When the change reads text that a person writes, such as an intent section or a list in a markdown file, don't expect the product owner to follow formatting rules. Write requirements so that:
   - **Claude owns the format.** The template and the skill that writes the file state the convention, and Claude applies it. The product owner talks and decides; they never format.
   - **Parsing fails safe.** Text the parser doesn't recognise is treated as the riskier case (for example "has open questions"), never as "nothing there".
   - **CI flags what it can't read**, as a warning rather than an error, so Claude or the engineer fixes the wording and the product owner never has to.
4. Do not resolve open questions or policy conflicts yourself. List them for the product owner.
5. Run `make validate`.

Do not write a plan or code.

## For a bug

A bug gets a short spec.

1. Read `bug.md`, `CLAUDE.md`, the existing spec of the feature it breaks (if there is one), and the code involved.
2. Copy `.sdlc/templates/bug-spec.md` to `changes/<slug>/spec.md` and fill it in:
   - **Requirements:** the correct behaviour, one per symptom in `bug.md` (R1, R2, …).
   - **Acceptance criteria:** one test per symptom, which fails today and passes once fixed, each a `- AC<n> (R<n>): …` bullet. A requirement with more than one outcome needs each one tested (the clause coverage rule above).
   - Add **Policy concerns** only if a policy skill applies to the fix, and **Out of scope** only if the fix deliberately leaves something alone.
3. If the bug reveals that the intended behaviour was never specified, or needs a product decision, say so under an **Open questions** heading for the product owner rather than deciding it.
4. Run `make validate`.

## Committing

When you commit, add `changes/<slug>/spec.md` by explicit path, never `git add -A` or `git add .`. Follow the `agent-identity` skill for commit trailers and PR signatures.
