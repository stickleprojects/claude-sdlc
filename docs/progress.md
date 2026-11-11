# Progress

Status as of 2026-11-11 (v0.9.1). This is a living log: update it whenever the pipeline changes or a stage is paused.

## Two kinds of repo

- **claude-sdlc (this repo): the framework.** Its own changes go through `fix:`/`feat:`/`ci:` PRs and `pipeline` issues. It's tested by unit and scenario tests and agent evals (see the readme's *Working on the framework*), and released as tagged versions with generated release notes and upgrade steps.
- **Consumer repos: the products.** [sdlc-sandbox](https://github.com/stickleprojects/sdlc-sandbox) is the public practice product (*StreamLite*, TypeScript). Real projects in Python and Godot run on the pipeline too, and many framework changes come from what they found. They pull the framework with `/sdlc` or `make sync-sdlc`.

## Where we are

| Stage | Status | Notes |
|---|---|---|
| Plan: intent | ✅ Works | `/intent`, for features and bugs (`bug.md`) |
| Design: spec | ✅ Works | *Spec from intent* opens one spec PR per change. The product owner works through the review with `/pr`, in plain language, deciding only product questions |
| Build: plan + code | ✅ Works | `/plan` in plan mode; `/build` builds small plans in one session and larger ones milestone by milestone from an approved `build.md`, or all of them with `/build all` |
| Test | ✅ Works | `make check`, coverage per suite in consumer builds, the verifier (per criterion, per clause, and delivery against each requirement), agent evals before every release |
| Deploy | ✅ Works | Claude review on every PR, `/pr` walkthroughs, the production gate, and optional auto-merge after a person's approval |
| Maintain | Not built | #15 |

## What works

- **CI** (`make check`): lint, about 600 tests, artifact validation (required sections, approved descopes, a definition of done, readable requirements and criteria in new work), and a check that scripts are committed as executable.
- **AI PR review**: follows [REVIEW.md](../REVIEW.md). It quotes the text each finding refers to, says who decides, and keeps one summary comment. It also checks every clause of a requirement against the criteria and the plan, with a cheap per-requirement clause check in CI.
- **Skills**: six entry skills (`/intent`, `/plan`, `/build`, `/pr`, `/next`, `/sdlc`) route each change to the right next step.
- **Guardrail hooks**: protected paths, format on edit, and a production gate (no deploys to production, no pushes to `main`, no merges or approvals by the agent). A bug's failing test locks once it's committed.
- **GitHub setup**: branch protection, CODEOWNERS, the token secret, Actions permissions, labels, `.gitignore` and the agent's own App identity, all scripted in `scripts/bootstrap-github.sh`.
- **Upgrades**: `/sdlc` syncs with three-way merges of local edits, and carries out each release's upgrade steps with the person.

## Earlier: product-owner review (since reworked)

*This was paused on 3 Nov and has since been reworked. The `po-review` walkthrough (reached through `/pr`) now explains each finding in plain language and asks the product owner only product decisions. The minutes idea below wasn't built. It's kept as the record of why the flow changed.*

**What happened.** `/po-review 6` (the spec for what is now #27) asked the product owner to rule on findings like *"A8 depends on the stage name"*. That question only makes sense if you've read the spec, and the product owner hadn't opened any files. The flow was built around review findings when it should be built around the product owner's understanding.

**What we learned.**
- The review sends testability and spec-wording findings to the product owner. Those findings belong to the engineer, or are tidy-ups Claude can make itself.
- The product owner needs to **understand the change first**, and only then make decisions.
- Bare IDs (A8, R2) mean nothing to the reader, even with the text quoted.

**Next piece of work (not started): "Product owner understands and challenges the change".** The product owner reads the intent and spec, or has Claude explain them, until they understand what will happen. Then they review the open questions, or interrogate Claude to find loopholes. Rough shape:

1. **Understand.** Claude explains the change in user terms: what users will see before and after, with examples, and what is deliberately out of scope.
2. **Interrogate.** The product owner asks free-form questions ("what if an intent has no questions section?", "could this break existing changes?"). Claude answers from the intent and spec, and says plainly where the spec doesn't cover something. Each gap becomes a decision or an open question.
3. **Decide.** Only product decisions (behaviour, scope, priority), asked in user terms. Technical findings are fixed automatically, or routed to the engineer, and listed as tidy-ups the product owner can veto.
4. **Accept.** Merge on GitHub.

**Recording the session as minutes (direction agreed).** The Q&A matters because it shows the train of thought and can surface useful insights, but it mustn't clutter the intent or spec. Treat the session as a **minuted meeting between Claude and the product owner**, saved next to the change:

```
changes/0001-browse-catalogue/
  intent.md
  spec.md                       ← records outcomes only, each linking to the minutes
  minutes/
    2026-10-18-spec-review.md   ← the meeting
```

The minutes would follow roughly this shape:

```markdown
# Spec review: browse the catalogue
Date: 2026-10-18 · Attendees: Kieron (product owner), Claude · Artifact: spec.md @ <commit>

## Context
What was being reviewed, and the before/after picture Claude presented.

## Discussion
- **Q (PO):** What happens if an intent has no questions section?
  **A (Claude):** It reports 0. The spec covers this in its requirements.
- **Q (PO):** Could this break existing changes?
  **A (Claude):** The spec doesn't say. ⚠ Gap, raised as a decision.

## Outcomes
- **Decisions:** what the PO decided, each one also written into spec.md.
- **Tidy-ups accepted:** technical fixes Claude made, which the PO didn't veto.
- **Actions:** e.g. "Engineer: cover X in the plan".
- **Result:** accepted / changes requested / rejected.
```

So the artifacts stay short, the reasoning is still kept in version control, and a later reader (or Claude, when planning) can see *why* a decision was made.

Open questions for this work:
- Is this one session at the spec stage, or does it also run at the intent stage? If both, there would be one set of minutes per meeting.
- Should `/plan` and the AI review read the minutes as context, or only the outcomes written into the spec?
- Should `REVIEW.md`'s "who decides" gain an *auto-fix* category, so spec-wording findings never reach the product owner?
- Should `sdlc check` validate the minutes, for example that an *Outcomes* section exists?

Until this is designed, try it on a sandbox change rather than in this repo.

## Field trial: jobhunt-app (3 Nov 2026)

The first consumer repo set up for a real product, outside the sandbox: [jobhunt-app](https://github.com/stickleprojects/jobhunt-app), a read-only browser over the markdown job-search data in a separate repo. Set up from scratch with the readme, then a first intent taken from a design brief to a PR ready to merge (jobhunt-app#4). These are practical results, in the order they came up.

**Setup** (fixes collected in #39):

| What happened | Lesson |
|---|---|
| `make check`: *No rule to make target* | The readme's step 2 block looks self-contained, so step 1 (write your `Makefile`) got skipped. Nothing warned |
| The new repo's branch was `master` | CI, *Spec from intent* and branch protection all assume `main`; nothing checks it |
| `__pycache__/` left untracked | No `.gitignore`; a dirty tree blocks the next sync |
| Token prompt looked frozen | It waits silently for an empty line after the paste |
| `gh secret set --org` returned 404 | `stickleprojects` is a user account; there are no organisation secrets, so each repo needs its own copy |
| No `CLAUDE.md` | By design the sync doesn't bring one, but nothing prompts for it before the first `/intent` |
| `make new-change role-index` and `name=` failed | The error comes from `sdlc new`, not a usage line naming `NAME=` |

About a dozen manual steps, with an assistant diagnosing each failure. A new user wouldn't have got through alone, hence #39's ask for a guide in the consumer repo and one re-runnable setup script.

**Where the pipeline fits:**
- **A data repo can't go on the pipeline.** The job-search repo is markdown written by an unattended 06:00 sweep, a Telegram bot and interactive sessions, all committing straight to `main` (1,000+ commits). The production gate and branch protection would break that, and the sync would overwrite its `.claude/settings.json` (#31). The app went in a new repo and reads the data repo by path.
- **CI reads every PR, so personal data stays out.** The design brief named contacts, confidential employers and family; it was redacted in a PR and the consumer's `CLAUDE.md` now forbids real personal data, with made-up fixtures for tests.

**Agents and hooks:**
- **Other agents run our hooks.** GitHub Copilot in VS Code picked up `.claude/settings.json` and reported the pre-edit hook as *errored* (exit code 0), then refused the edit. The hook itself ran cleanly by hand. Failing closed is right, but the message pointed at the wrong cause.

**Intent stage:**
- **The split test was contaminated.** The whole brief went in as one change to see how `/intent` breaks it down, but the engineer's answers (read-only, no database) set the scope before the skill had to. A clean test needs an eval case with the brief alone.
- **Claude added an `## Out of scope` section on its own.** The template has none, so cut features could simply vanish. Evidence for adding the section to the template (a required-sections change, so it affects every consumer).
- **The first draft promised *confirmed* duplicates in a read-only app,** and said *Open questions: None* while it had decided home-network access on the product owner's behalf. Both were caught in human review, not by the skill. The skill could ask whether each outcome fits the constraints, and send any decision it made for the originator to Open questions.
- **The intent PR's AI review passed with 0 findings** on the corrected draft. It checked the rules (read-only, no outbound, no copied data) but has no view of earlier drafts.

**Product owner experience:**
- **Clunky in VS Code.** Skills and PR approval assume an engineer's tools; the product owner's job is small and the tooling is the hard part. Options, starting with GitHub comments and `@claude po-review`, are in #40.

**Spec stage:**
- **Spec from intent worked end to end** for the first time: merging the intent generated the spec, `make validate` passed inside the run, and the workflow opened the spec PR itself (jobhunt-app#5; #13).
- **The spec review earned its keep.** It found two real gaps: loopback-only binding without a `Host` check (DNS rebinding could expose contacts), and a no-personal-data-in-logs rule that no test enforced. The product owner agreed by replying `@claude` on the findings, and Claude applied both.
- **`@claude` can't check its own work.** The mention workflow has no `--allowedTools`, so `make check` needed an approval nobody could give; CI caught it instead. The review summary also stays stale after the fix until someone adds the `review` label. Both are on #40.

**Plan stage:**
- **Approving a plan skips `/plan`.** Claude Code's plan-mode dialog offers to leave plan mode and start building; nothing makes the engineer save and commit `plan.md` first. Here the engineer chose "keep planning", switched the mode selector by hand, and is watching that the session never goes to edit or auto mode until `/plan`. The rule needs a hook (#44).

## Pipeline issues

Open gaps and ideas are tracked as GitHub issues labelled [`pipeline`](https://github.com/stickleprojects/claude-sdlc/issues?q=is%3Aopen+label%3Apipeline). The release notes record what each version fixed.

## History

| PR | What | Lesson |
|---|---|---|
| #1 | Switch CI to a Pro subscription token | Identity federation or an API key would need separate API billing |
| #3 | Allow the review to post comments | Automation mode only permits the tools in `--allowedTools` |
| #4 | Commit scripts as executable | On NTFS, `chmod` doesn't stick, and a non-executable hook **silently** disables the guardrail |
| #5 | Exempt maintenance PRs from the artifact-chain review pass | Not every PR needs intent, spec and plan |
| #7 | Pass allowed tools to the agent in CI | CI workspaces are never trusted, so the allow list in `settings.json` is ignored there |
| #8, #9 | CODEOWNERS; production gate checks only push arguments | Whole-command matching blocked a legitimate `git merge main && git push` |
| #16 | Readable findings, one summary comment, `/po-review` | Findings need quoted context; the first `/po-review` design was wrong (see above) |
| #17 | Bootstrap script and *Getting started* | Roughly ten manual GitHub settings broke setup; now scripted |

Setup problems that weren't code: a token pasted with line wraps (the secret was cut off); the Claude GitHub app not installed; and the action skipping itself on PRs that change its own workflow file.

Later work:

| PR | What | Lesson |
|---|---|---|
| #19 | Pipeline commands go through `make` (`new-change`, `status`) | `uv run sdlc` in skills tied every consumer to Python |
| #21 | Framework tests (hooks, scripts, scenario), PR-title check, versions from PR titles, release notes, `sync-sdlc` | Once product work moved out, framework CI was checking the wrong things |
