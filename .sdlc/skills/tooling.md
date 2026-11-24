# The tooling path (#221)

Read this only when the repo's `CLAUDE.md` has a `Tooling paths:` line. Without the line the path is off, and none of this applies. A tooling change (scripts, CI support, dev tools) goes through one PR that carries its intent, plan and code, with no spec. `.sdlc/docs/tooling-path.md` explains it for people.

## Intent (`sdlc-intent`)

- **When to offer it:** the change is only scripts, CI support or dev tools, every file of its code is inside the `Tooling paths:` entries, and nothing about how the product behaves changes. Then offer the path in one line ("this only touches `scripts/`, so one PR can carry the intent, the plan and the code, with no spec"). The person can refuse it. Take the full path if any part is product code, or if you're not sure. <!-- rule: tooling.offer -->
- **Draft the intent** as for any change, and show the person the file for corrections. `Product owner:` names whoever owns the tooling, usually an engineer. Under it, add the line `Kind: tooling`, on its own and outside any comment. CI and `make next` read it.
- Commit `intent.md` and `change.toml` (`chore(<slug>): intent`) on `build/<slug>`, from `origin/main`, number included, and push. Open no intent PR: the one PR comes with the code. Then hand over to the `sdlc-plan` skill (Skill tool, passing the slug). <!-- rule: tooling.intent-branch -->

## Plan (`sdlc-plan`)

- **Plan from the intent:** there's no spec, so each **Proposed outcome** statement is an acceptance check. It gets a design statement and a Verification row that would fail if it weren't met, in place of the clause work. The code stays inside `Tooling paths:`. If a step needs code outside them, or changes how the product behaves, it isn't tooling. Stop and offer the full path: drop `Kind: tooling`, and the intent goes in through its own PR. <!-- rule: tooling.plan -->
- **Save the plan** with the base line `Spec: none (tooling path)`, commit `plan.md` on the change's `build/<slug>` branch, and push. Open no plan PR. Hand over to the `sdlc-build` skill on the same branch: merging the one PR approves the intent, plan and code together. <!-- rule: tooling.same-branch -->

## Build (`sdlc-build`)

- A candidate is an `origin/build/<slug>` with `intent.md` (`Kind: tooling`) and `plan.md` committed, and no merged PR from it. Its plan is approved with its PR, not on `main`. Build it as a small build, on that branch.
- The PR is titled `chore(<slug>): <summary>`, or `ci(<slug>): <summary>` for CI work. Its body opens by saying that merging it accepts the intent, plan and code together, and that the engineer decides. <!-- rule: tooling.pr -->

## Verify (`sdlc-verifier`)

- There's no spec, so read `intent.md` in its place. The **Proposed outcome** statements are the acceptance criteria, each checked through its Verification row, and there are no requirements to split into clauses. A statement that no row checks is a FAIL. <!-- rule: tooling.verify -->
