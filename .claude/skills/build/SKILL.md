---
name: build
model: sonnet
effort: medium
description: Stage 3 (Build), after /plan. Build a change from its merged plan.md. A small plan is built straight away in one session; a larger one first gets a build plan (build.md) that the person approves as a file, then one milestone per session. Checks that the previous session finished (committed, pushed, tests passing) before doing more. "/build all" runs every remaining milestone in turn, each in a fresh subagent, through to the PR. Use when someone says "/build", "/build 0001", "/build all", "start the build", "continue the build", "next build step" or "build the rest".
---

# Build a change

How much ceremony a build gets depends on its size:

- **Small** (most bug fixes, copy changes, a few files): built in **this session**, straight from plan.md, ending in one PR. No build.md, no milestones, no approval round. The plan was already approved.
- **Large** (more than one session's work): first a **build plan**, `changes/<slug>/build.md`, which splits the plan into milestones. The person reviews it as a file and approves it. Then one milestone per session, and one PR at the end.

Milestones are sessions, not PRs. Every build, small or large, ends in exactly one PR.

For a large build the chat holds nothing between sessions. All state lives in git: the branch `build/<slug>` and `changes/<slug>/build.md`.

## Ways this skill runs

- **Single (`/build`, `/build 0001`):** this session does one unit of work, then stops. A unit is: a whole small build; writing and approving the build plan; one milestone; or repairing what the previous session left unfinished. For the next unit the person starts a new conversation (or types `/clear`) and runs `/build` again.
- **All (`/build all`, `/build all 0001`):** this session doesn't write code. It runs each unit in a fresh subagent until the PR is open or something needs the person. See [Running every milestone](#running-every-milestone-build-all). A small build just runs in this session.
- **Worker:** a subagent started by `/build all`. It does one milestone and never asks the person directly. See [Worker mode](#worker-mode).

Ask whenever something is ambiguous, but **one decision at a time**. Use AskUserQuestion for a single decision with your recommendation first (a worker returns the question instead). Never use it to review a list, a breakdown or a document: put that in a file and ask the person to read the file. Never guess on:
- which change to build;
- what to do with leftover work;
- a plan that doesn't hold up.

## Rules for every session

- **spec.md is never edited on a build branch.**
- **plan.md isn't edited here either.** If the plan is wrong or can't be built, stop and ask, offering to send the change back to plan (`/plan`, which amends it through a plan PR; build.md then goes back to draft). A small implementation detail can be recorded as a deviation for the engineer. Anything that changes behaviour or a Verification row needs a plan PR first.
- **Follow `.claude/skills/scope.md`.** Silence is not permission, and a rule's scope is a minimum. Never leave something undone, untested or unchecked (a descope) unless plan.md's Risks records it with an `Approved:` line, or the engineer has answered it as a deviation. That includes descopes carried forward from earlier milestones or neighbouring code ("not tested, like the rest of …"): each new piece of work meets the bar on its own. Test each criterion at the level it describes; a UI criterion is tested through the UI. In a single session, ask; a worker returns `BLOCKED`.
- **Follow CLAUDE.md**, including any repo-specific rules about data, fixtures and outbound actions.
- **Follow the `agent-identity` skill** whenever you commit, push, open the PR or post on GitHub: the `Requested-by:` trailer, signing with `— Claude` (or `(posted from Claude Code)` when acting as the person), no @-mentions, and fetch-and-merge before every push.
- **Commit by explicit path** (`git add <file> …`), never `git add -A` or `git add .`. Check `git status` before each commit.
- **Commit and push after each plan step,** so a dropped session loses little.
  - Code commits: `feat(<slug>): <what>` (in a large build, `feat(<slug>): M<n> <what>`).
  - Commits that only change build.md: `chore(<slug>): <what>`.

  These messages reach `main` when the PR merges with a merge commit. That's why they don't use `build(...)`, which in conventional commits means build-system changes.
- **Merge, never rebase, on `build/<slug>`.** build.md records commit shas, and a rebase rewrites them all, so every `done` milestone would reopen. Bring in `origin/main` with `git merge`.
- **Bug fixes: the failing test comes first, then it's locked.** If the plan's first step is a failing test (per the `plan` skill):
  1. The first commit is the failing test on its own: `test(<slug>): failing test for <symptom>`. Push it. For a change with `bug.md`, that commit locks the files it touched: the protect-paths hook asks `scripts/tests-locked.sh` on every edit. New tests in other files (coverage, regression guards) can still be written.
  2. Those test files must not change. In a large build, record them in build.md's **Locked tests** line (`<sha>`: the files) and add `git diff --exit-code <sha> -- <files>` to the **Done when** of every milestone. The checks then catch an edit in every later session, whatever the session's environment.
  3. In a small build, run that same `git diff --exit-code` before opening the PR.
  4. If the repo has its own lock as well (a mechanism CLAUDE.md names), use it too. The `git diff` check also catches an edit made some other way than the edit tools, such as `sed`. If the test itself is wrong, stop and ask; never edit it to get past the check.
- **Flaky tests are bugs. Fix them; don't rerun past them.** A test is flaky if it fails and then passes on a rerun with no change, or passes on its own but fails in the full suite. When you see one:
  1. **Reproduce it.** Run it repeatedly, for example 20 times: on its own, in the full suite, and under load (parallel workers, a cold cache).
  2. **Find the cause.** Usually timing (real timers, sleeps, tight timeouts), state shared between tests, the real clock, async work that isn't awaited, network, or a cold cache.
  3. **Fix the cause, not the symptom:** fake timers, waiting on the condition, isolated state, a fixed clock. A longer timeout or a retry is a fix only if you've shown that the slow path is slow by design.
  4. **Show it's fixed.** The same repeated run passes every time.

  **Try at least three different approaches before giving up.** If it's still flaky after that, record it under **Flaky tests** in build.md (or in the PR body for a small build): the test, how it fails, how often, each approach and its result, and `Engineer decides: yes`. Never skip a test, quarantine it or wrap it in retries without the engineer's agreement.
- **Coverage is part of every build, in every language.** Every build runs `make coverage`, which runs each test suite with coverage and fails when a suite is below its threshold. The thresholds live in the stack's own config (for example `pyproject.toml`, `package.json`).
  - **No `make coverage` yet:** a large build's first milestone adds it for every language in the stack (the tool as a pinned dev dependency, the thresholds, coverage output in `.gitignore`). Default thresholds: 90% lines and 80% branches per suite. A small build doesn't add it; it says in the PR that the repo has no coverage target.
  - **Below a threshold: write the missing tests.** Never lower a threshold or add an exclusion to get green. Generated code, test helpers and the tests themselves may be excluded; record each exclusion as a deviation with `Engineer decides: yes`.
- **Stay inside the current unit.** Don't start the next milestone, even with time left.
- **If context is getting heavy before a milestone is done:** commit and push what is finished and tested, write precise notes in build.md (what's done, what's next, any decision half-made), leave the milestone `in progress`, and stop.
- **Use `gh api` (REST) for GitHub.** `gh pr create`, `gh pr edit` and `gh issue view` use GraphQL, which fails in some orgs and in cloud sessions. Open a PR with `gh api repos/{owner}/{repo}/pulls -f title=… -f head=build/<slug> -f base=main -f body=…`, and check the result.

## 1. Work out which change to build

1. `git fetch --prune origin`.
2. **If the person named a change** (`0001` or `0001-role-browser`), use it, unless it isn't ready to build: not planned yet (offer `/plan`), or already built and merged (say so).
3. **Otherwise, list the candidates.** A candidate is a folder `changes/<slug>/` where all of these hold:
   - `plan.md` exists on `origin/main`;
   - no merged PR has come from `build/<slug>`. Check with `gh api 'repos/{owner}/{repo}/pulls?state=closed&head={owner}:build/<slug>'` and look at `merged_at`.
   - **One candidate:** use it, and say which.
   - **Several:** ask which. Put any already in progress (an `origin/build/<slug>` branch exists) first.
   - **None:** don't just stop. Follow routing step 4 in `.claude/skills/routing.md`: if a change is ready to plan (its spec merged), say so and offer to run `/plan` for it; otherwise say what each change is waiting on.

   `make next REF=origin/main` (see the routing file) lists every change's next step, which gives you the candidates directly.
4. **Check the plan is approved.** It must be merged on `origin/main`. If an open PR changes this change's `spec.md` or `plan.md`, ask whether to wait for it or build against what's on `main`.

## 2. Get onto the branch and check what the last session left

1. **Get onto the branch.** If `origin/build/<slug>` exists, check it out and fast-forward to it. Otherwise create `build/<slug>` from `origin/main`. If the session was started with `--worktree`, switch the worktree to that branch.
2. **Uncommitted changes** mean the last session stopped mid-step. Show `git status`, `git diff --stat` and any in-progress notes from build.md, then ask: **keep and continue** (the tests must pass before anything is committed), **stash**, or **discard** (after showing what would be lost).
3. **Local commits not on origin:** say so, and push them once the checks pass.
4. **The spec or plan changed on main after the build plan was made.** Check with `git log <built-against sha>..origin/main -- changes/<slug>/spec.md changes/<slug>/plan.md`. If either changed, show what changed, merge `origin/main` into the branch, and update build.md for it as a draft (section 4): changed milestones need approving again.

Then:
- **No build.md, and nothing built yet:** size the build (section 3).
- **build.md is a draft** (`Status: draft, awaiting approval`): it isn't approved. Never build from it. Go to section 4.
- **build.md is approved:** section 5.
- **`Status: PR open`:** see [When build.md says PR open](#when-buildmd-says-pr-open).

## 3. Size the build

Read CLAUDE.md, then `intent.md` (or `bug.md`), `spec.md` and `plan.md` in full. Decide whether this is one session's work.

**Small: build it now** when all of these hold:
- the plan has at most three steps;
- it touches a handful of files (as a guide, five or fewer, not counting tests);
- it adds no new dependency, service, screen or data format;
- you expect to build, test and open the PR comfortably within this session.

Changing the text of a message, fixing a one-line bug or adjusting a style is small. When it's borderline, prefer small: a build that runs out of room can still write a build plan from where it got to.

**Large: write a build plan** otherwise. Say which you chose and why in one line, then go on. In `/build all`, a small build runs in the orchestrator's session itself.

### 3a. Small: one session, one PR

1. Build the plan's steps in order, committing and pushing after each (`feat(<slug>): <what>`; the bug-fix test first, as above).
2. Run `make check`, `make coverage` (if the repo has it) and every command in the plan's Verification section. All must pass. For a bug fix, also the `git diff --exit-code` on the test.
3. Finish as in section 6: the verifier, then the PR. The PR body says it was built in one session without a build plan.
4. Report: what was built, the test counts and coverage, any deviation, and the PR link.

If it turns out bigger than it looked, stop at the end of a finished, passing step, commit and push, then write a build plan (3b) whose first milestone records what is already done.

### 3b. Large: write the build plan as a draft file

1. **Split the plan's Steps into milestones.** Each milestone is what one fresh session can build, test, commit and push, usually one to three plan steps, with its own passing tests.
   - **Aim for two to eight milestones.** One milestone means the build is small: use 3a. More than eight means the change is probably too big; add a question recommending it be split into several changes, and let the person decide.
2. **Plan for something to show.** Give each milestone a **Demo** line: what a person can see or click once it's done, or "nothing, backend only". Fill in **First demo** in the header. If nothing visible arrives until more than half the milestones are done, prefer a vertical-slice order (a thin path through every layer first, then fill in). If you keep a backend-first order, add a question saying so, with the slice as the alternative.
3. **For each milestone, record:**
   - a one-line **Goal**;
   - the plan steps it covers;
   - the acceptance criteria whose Verification rows it makes pass, marking partial ones;
   - **Done when:** `make check`, then `make coverage`, plus the exact commands from those Verification rows (and the locked-test diff for a bug fix). `make check` runs every test so far, so a milestone that breaks earlier work fails its own check.
4. **Set up coverage.** If there's no `make coverage` target, the first milestone adds it, and `make coverage` joins each Done when from then on. Record the thresholds in the **Coverage** line.
5. **Check criteria coverage.** Every acceptance criterion in spec.md must be fully passed by some milestone. The last milestone always includes `make check`, `make coverage`, the `verifier` subagent and the PR.
6. **Collect everything the person must decide** in **Questions before approval**, each with its options and your recommendation:
   - a plan gap, or a plan that's contradictory or not buildable as written (options: pause for a plan PR, or record a deviation);
   - any reading you had to take of an ambiguous plan;
   - every deviation from the plan, each one separately;
   - every descope (`scope.md`) in the plan without an `Approved:` line, and any the build would add, each one separately;
   - more than eight milestones, or a backend-first order.

   Never put a decision in a milestone's notes, and never fold one into "approve". Anything that would change the spec belongs to the product owner: say so and stop, without writing the draft.
7. **Write `changes/<slug>/build.md`** from `templates/build.md`, on `build/<slug>`, with `Status: draft, awaiting approval`, `Approved: not yet` and the `origin/main` sha it was built against.
8. **Run `make validate`, then commit and push the draft** on its own (`chore(<slug>): draft build plan`). It's committed so that a session that ends now loses nothing; its draft status stops any session building from it.
9. **Ask for approval of the file** (section 4).

## 4. Approving the build plan

1. **Ask the person to review the file, not the chat.** Give them its path and a short summary only: the number of milestones, the first demo, the coverage thresholds, and how many questions wait for them. Then ask them to read build.md and either approve it or say what to change. They may edit the file themselves.
   - Don't repeat the breakdown or the questions in the chat, and don't put them in AskUserQuestion.
   - Wait for their reply. Apply each change (re-read the file first if they edited it), commit and push it, and ask again. Repeat until they approve.
   - Each answer to a question moves to where it belongs (a milestone, or **Deviations**). **Questions before approval** reads `None.` before approval.
2. **On approval:** set `Status: in progress` and `Approved: <their name>, <date>`. Run `make validate` (it fails on an approval with open questions), commit `chore(<slug>): approve build plan`, and push.
3. **Stop.** In a single session, tell the person: start a new conversation, then run `/build`. In `/build all`, go on to the loop.

## 5. build.md is approved: check the previous session, then do the next milestone

1. **Check the finished milestones.** For each milestone marked `done`, its recorded commit must be on `origin/build/<slug>` and an ancestor of `HEAD`.
2. **Re-run the checks.** Run `make setup` if dependencies are missing. Then run `make check`, `make coverage` and the **Done when** commands of every `done` milestone.
   - **A build.md written before these rules** (no **Questions before approval**, **First demo**, **Demo** lines or **Coverage** line, or no `make coverage` in Done when): bring it up to date before new work, from `templates/build.md`. Add `Approved:` with the person who approved the original breakdown if build.md or the git log says who; otherwise ask. Commit as `chore(<slug>): update the build plan to the template`.
3. **If anything fails, or a recorded commit is missing:** mark that milestone `reopened` with the reason. This session's work is to fix it: fix, re-run the checks, commit `feat(<slug>): M<n> fix <what>`, update build.md and push. Don't start new work until everything already done is green again.
4. **Flaky tests that earlier sessions noted** and nobody fixed or handed over are repair work for this session, before new work.
5. **Pick the milestone:** one marked `in progress` (continue from its notes and commits), otherwise the first `todo`. Say which, and what it covers, before starting.
6. **Build it, step by step, from the plan.** Commit and push after each step. Keep the milestone's notes current. Record each deviation under **Deviations** with its reason and whether the engineer needs to decide.
7. **Finish the milestone.** Run its **Done when** commands; all must pass. Mark it `done` with the last code commit's short sha, the date, the test count and the coverage per suite. Add a line to the session log. Commit build.md, push.
8. **Report in a few lines:** what was built, what a person can now see (its Demo), the test counts and coverage, any deviations or questions, the next milestone, and "Start a new conversation, then run `/build`" (a single session only; a worker returns its report instead).

## 6. Finishing: verify and open the PR

For a small build after its steps, and for a large build as part of its last milestone:

1. **Run `make check` and `make coverage`.** Both must exit 0.
2. **Run the `verifier` subagent** on `changes/<slug>`. Fix any FAIL that's within the plan. If a fix would change the plan or the spec, stop and ask.
3. **Open the PR** with `gh api` (see the rules above), then run `scripts/auto-merge.sh <N>` on it (the `agent-identity` skill).
   - Title: `feat(<slug>): <summary>` (a change with `bug.md`: `fix(<slug>): <summary>`).
   - Body, in this order, so the reviewer sees what needs a decision first: the descopes, each quoted with who approved it; the deviations; the plan's manual end-to-end steps, for the engineer; then what was built; the verifier's per-criterion results; the coverage per suite against its threshold. End it with the attribution line the session asks for.
   - Don't add the `review` label. The review already runs when the PR opens.
4. **Large build:** record the PR in build.md (`Status: PR open (#N)`), commit and push.
5. **Never approve or merge.** A person merges.

## When build.md says PR open

Report the PR's state: checks, and the latest review summary with its open findings. Don't start new work.

- **Merged:** the build is complete. The PR's merged state is the record; build.md isn't updated.
- **Review findings need code changes and the person asks this session to make them:** treat them as a `reopened` milestone. Make the fix, run the checks, push, and add the `review` label if the repo's review workflow uses one and it isn't already on, so the latest push gets reviewed.

## Running every milestone (`/build all`)

This session is the **orchestrator**. It starts one worker subagent per milestone, reads each report, and starts the next. Each worker begins with an empty context, as a new conversation would.

1. **Work out the change** (section 1), asking the person as usual.
2. **No build.md:** size the build here (section 3). A small build is built here (3a), and that's the whole run. A large build's plan is written and approved here (3b and 4), because it needs the person. Then go on to step 3.
   **A draft build.md:** get it approved here first (section 4).
3. **Run the loop.** Start each worker with the Agent tool, `subagent_type: general-purpose`, `model: sonnet`, in the foreground, with this prompt:

   ```
   You are a /build worker for change <slug>. Read .claude/skills/build/SKILL.md and follow it in
   worker mode: do exactly one unit of work, then return the report it describes.
   <any answers from the person, or verifier results, for this unit>
   ```

   Then act on the first line of its report:
   - **`DONE`:** `git fetch` and confirm build.md on `origin/build/<slug>` marks that milestone `done` and its commit is on the branch. Tell the person in one line any descopes and anything marked `Engineer decides: yes` first, then what was built, what they can now see, the test counts and the coverage. Start the next worker.
   - **`BLOCKED`:** ask the person the worker's question with AskUserQuestion, recommendation first. Start a new worker with the answer in its prompt.
   - **`READY-FOR-VERIFY`:** run the `verifier` subagent on `changes/<slug>` from this session (workers can't start subagents). An unapproved descope: ask the person about each one first (build it, or approve it), and pass the answers on. Any other FAIL: start a worker with the report to fix the FAILs within the plan, at most two rounds, then ask the person. No FAIL: start a worker with the per-criterion results to open the PR.
   - **`PR-OPEN`:** the build is finished.
   - **`FAILED`:** stop and show the person the report.
4. **Stop when** the PR is open; a worker reports `FAILED`; two workers in a row leave build.md unchanged; or the number of workers reaches the number of milestones plus three.
5. **Final report:** first the descopes, anything marked `Engineer decides: yes` and the plan's manual end-to-end steps; then each milestone done in this run with its commit, the test counts and the PR link; and what's left for the person: review the PR, run those steps, merge.

## Worker mode

A worker follows sections 1, 2, 5 and 6 like a single session, with these differences:

- **The change is the one named in the prompt.**
- **No build.md, or a draft one:** return `BLOCKED`, saying the build plan is missing or not approved. Never build from a draft.
- **Never use AskUserQuestion.** Wherever this skill says to ask: commit and push only what is finished and passing, write the half-made decision into the milestone's notes, commit and push that, and return `BLOCKED`.
- **A descope nobody approved:** if the milestone would leave something undone, untested or unchecked (`scope.md`) that plan.md's Risks doesn't approve and no answer in your prompt covers, return `BLOCKED`. Don't take the plan's or an earlier worker's word for it, and don't report `DONE` with it written into the notes. Options: build it to the bar (recommended unless it's far outside the plan), approve the descope, or send the change back to `/plan`.
- **Uncommitted changes from a previous session:** return `BLOCKED` with keep, stash and discard as options and your recommendation.
- **The last milestone:** do its own steps and section 6 step 1, then return `READY-FOR-VERIFY`. With the verifier's FAILs in the prompt, fix those within the plan and return `READY-FOR-VERIFY` again. With a clean result, do section 6 steps 3–4 and return `PR-OPEN`.
- **Return this report**, and nothing after it:

  ```
  <DONE | BLOCKED | READY-FOR-VERIFY | PR-OPEN | FAILED>
  Unit: <M<n> name, or "repair M<n>", or "flaky test fix">
  Commits: <short shas pushed in this unit>
  Tests: <counts from the Done when run>
  Coverage: <per suite, against its threshold>
  Demo: <what a person can now see, or "nothing, backend only">
  Descopes: <each one with who approved it, or "none">
  Engineer decides: <deviations or flaky tests marked yes, or "none">
  Question (BLOCKED only): <one question>
  Options (BLOCKED only): <2–4 options, recommended one first, each with its consequence>
  Detail: <a few lines; for FAILED, the failing command and its output tail>
  ```
