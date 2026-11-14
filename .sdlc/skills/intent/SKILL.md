<!-- The frontmatter for this skill is in .claude/skills/sdlc-intent/SKILL.md, which Claude Code reads. Projects change this
file with an override in .sdlc-local/ (see .sdlc/docs/overrides.md), never by editing it. -->

# Draft an intent (or a bug report)

**Is it new?** Run `make next REF=origin/main` (see `.sdlc/skills/routing.md`). If the person names a change that already exists, or describes one that's already in the list, don't draft a second one: say where that change is, and offer its next step (routing step 4), or a new intent if they really mean something different.

**Is it a bug?** If the person describes something that worked differently from what was specified or expected (found in testing or use), it's a bug: use the lighter path in [For a bug](#for-a-bug). That includes pushback on a change that has already merged or shipped: it becomes a new bug change with `Came from:` naming that change, never a reopened one. If it's new behaviour, or you're not sure, ask.

1. Act as a business analyst. Ask short questions until you understand: the problem and who has it, the outcome that would count as success, the users and systems affected, constraints, and what is still unknown. Ask one round at a time; don't invent answers.
2. Pick a short kebab-case name and run `make new-change NAME=<name>`. It prints the new `intent.md` path.
3. Fill in every section of that file from the conversation. Put anything unresolved under **Open questions** rather than guessing.
4. **If the repo has a roadmap** (`docs/roadmap.md`), place the change on it. Read the roadmap and agree with the originator which milestone this delivers: usually the first one that isn't done and whose scope covers it. Then, in the same PR:
   - add `Milestone: M<n>` to the intent, under `Product owner:`;
   - add the change's row to that milestone's `### Changes` table as `| [<slug>](../changes/<slug>/) | <summary> | planned |`;
   - if the change doesn't fit the milestone's agreed scope, or its scope isn't agreed yet (it's `draft`), or it moves a milestone's goal, exit criteria or order, add an adjustment record from `.sdlc/templates/roadmap-adjustment.md` at `docs/roadmap/adjustments/NNNN-<slug>.md` (the next free number, `Status: accepted`: merging the PR is the acceptance), an `Adjustment: NNNN-<slug>` line in the intent, and a citation of the record in the milestone's scope text. Never edit an old record away: a new one supersedes it.

   If it fits no milestone, ask the originator whether to add it to one (an adjustment) or to a new milestone; the order is the product owner's, so never reorder milestones yourself. The PR body gets a **Roadmap** section: the milestone by name (not just its number), whether the change delivers the whole milestone or part of it, what it knowingly leaves out, and any adjustment. Without a roadmap, skip this step.
5. Run `make validate`. With a roadmap, it fails until the row, the `Milestone:` line and any record agree.
6. Show the originator the file and ask for corrections. Remind them that the product owner accepts it by approving the PR. Merging that PR triggers spec generation.

Do not write a spec, a plan or any code at this stage. (A bug on the fast path, below, is the one exception.)

## For a bug

1. Ask only what `bug.md` needs: what happens, what should happen, the steps to reproduce (and whether it happens every time), where it was seen, and the change it came from, if any (`make next` lists them). Use made-up or described data, never real personal data.
2. **Choose the path.** If the repo's `CLAUDE.md` has the line `Bug path: full`, every bug takes the full path: skip to step 3 (`.sdlc/docs/settings.md`). Otherwise (`Bug path: fast`, or no line), read enough of the code involved to say where the cause is, then pick one:
   - **The fast path (the default, #148, #160):** one PR carries `bug.md`, its short spec, the failing tests and the fix, so approving it means the fix ships. Take it when all of these hold:
     - what should happen is clear, with no product decision open;
     - you've found the cause, or narrowed it to code you can name, and the fix stays inside that code;
     - it needs no new dependency or service, nothing the `sdlc-security-policy` skill covers, no architecture decision (an ADR's **Revisit when**, a new framework or datastore), and no migration of data that existing users or installs already hold;
     - you expect the fix, its tests and the PR to fit in this session.

     Size and file count don't count against it: a fix can touch ten files, add assets or data files, or change a format that only this code reads, and still take the fast path.
   - **The full path** otherwise: the bug PR, then its spec PR, plan and build, as for an intent.

   Tell the person which path and why in one line of plain words, for example "I can fix this in the same PR, so approving it ships the fix", or "this needs a product decision first, so the report goes in on its own". They can ask for the other path.
3. Run `make new-change NAME=<name> TYPE=bug`. It prints the new `bug.md` path; there is no `intent.md`.
4. Fill in every section, then run `make validate`. Show the person the file and ask for corrections.
5. **The full path:** open the bug PR, from any branch but `build/<slug>` (that one is the build's). Merging it triggers a short spec: requirements and one acceptance test per symptom.
6. **The fast path:**
   1. Work on `build/<slug>`, created from `origin/main`. The plan gate allows code there once `bug.md` and `spec.md` are committed.
   2. Write `spec.md` as the internal `sdlc-spec` skill's **For a bug** section says (read it with `.sdlc/scripts/resolve.sh skills/spec/SKILL.md`). If that raises an open question for the product owner, the fast path stops: delete `spec.md`, move `bug.md` to a branch of its own (`bug/<slug>`), say why, and take the full path. The spec workflow writes the spec once the bug merges, and the question goes to the product owner there.
   3. Commit `bug.md` and `spec.md` (`bug(<slug>): <title>`) and push.
   4. Build the fix with the `sdlc-build` skill (its **Bug fast path** section): failing tests first, then the fix, the verifier, and a PR titled `fix(<slug>): <summary>`. If the session is running short at this point, stop and say so. `/sdlc-build <slug>` picks up the branch in a new session.

## Committing

When you commit, add the change's files by explicit path (`git add changes/<slug>/intent.md` or `…/bug.md`, with `…/spec.md` on the fast path, plus `docs/roadmap.md` and any adjustment record), never `git add -A` or `git add .`. Follow the `sdlc-agent-identity` skill for the commit trailer and PR signature.
