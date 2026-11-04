# What each role does

Every change moves through one loop. Each stage commits a file that the next stage reads:

```
intent.md ──► spec.md ──► plan.md ──► code + tests ──► PR + review ──► release
  (Plan)      (Design)     (Build)       (Test)           (Deploy)
```

All three files live in one folder per change: `changes/NNNN-short-name/`. Claude drafts each one. People make the decisions at the gates between stages. Claude never approves its own work, and it can't deploy to production.

Find your role below. Each section covers when you're involved, what you do (with the commands), and the decision that stays with you.

| Role | Stage | You decide |
|---|---|---|
| [Originator](#originator) | Plan | What problem we're solving |
| [Product owner](#product-owner) | Plan, Design | Whether the intent and spec are accepted |
| [Engineer](#engineer) | Build, Test | Whether the plan is right and the code is done |
| [Tech lead / architect](#tech-lead--architect) | Design, Build | Higher-risk changes and the review policy |
| [Code owner](#code-owner) | Deploy | Whether the PR merges |
| [Release manager](#release-manager) | Deploy | Whether it goes to production |
| [Policy owner](#policy-owner) | Design | What the policy skills say |
| [Platform team](#platform-team) | All | Hooks, CI, settings and evals |

---

## Originator

**When:** You have a problem, a request or an idea. You don't need to be an engineer.

**What you do**

1. Start Claude Code in the repo and describe the problem:
   ```
   claude
   > /intent Customers can't tell whether their export finished
   ```
2. Answer Claude's questions about who's affected, what success looks like, and any constraints.
3. Claude creates `changes/NNNN-<name>/intent.md`. Read it and correct anything wrong: tell Claude, or edit the file yourself.
4. Commit it on a branch and open a PR:
   ```
   git switch -c intent/<name>
   git add changes/ && git commit -m "intent: <name>"
   git push -u origin HEAD && gh pr create --fill
   ```

**Found a bug?** Something that doesn't work as specified, found in testing or use, takes a lighter path. Describe it the same way:
```
claude
> /intent The export button spins forever on an empty list
```
Claude recognises it as a bug and asks only what happens, what should happen, how to reproduce it and where you saw it. It creates `changes/NNNN-<name>/bug.md` (by running `make new-change NAME=<name> TYPE=bug`) instead of an intent. Commit it on a `bug/<name>` branch with the message `bug: <name>`, and open a PR as above. Once it merges, a short spec is generated: one requirement and one acceptance test per symptom.

**Stays with you:** Saying what the problem is. If Claude adds something you didn't mean, remove it.

---

## Product owner

**When:** An `intent:`, `bug:` or `spec:` PR asks for your review. GitHub notifies you when it's opened. The spec PR is opened automatically when your intent merges. Each change gets its own spec PR, titled `spec(NNNN-<name>): …`.

> **Spec PRs need one click before their checks run.** They're opened by `github-actions[bot]`, and GitHub holds the checks and the review on PRs from that account until someone approves them. If the PR shows *Approve and run workflows*, click it.

**Where you work:** you can use two tools, which do different jobs.

| | Claude Code session | GitHub PR |
|---|---|---|
| Purpose | **Where you give feedback.** Claude explains each finding, asks for your decision, edits the artifact and replies on GitHub for you | **The gate.** Approving and merging *is* your acceptance, and it's the audit record |
| Use it for | Working through findings and open questions | Reading the review summary, then the final approve and merge |

You don't need to comment on GitHub yourself.

**What you do**

1. **Open the PR on GitHub** and read the single *Review summary* comment. It lists each open finding with the text it's about quoted, and who decides it. Findings marked *engineer* aren't yours.
2. **Work through your items** in Claude Code:
   ```
   claude
   > /po-review 6
   ```
   Claude goes through the items one at a time: it quotes the spec text, explains the problem, suggests a fix and asks what you want. Then it edits the artifact, records your decisions, pushes, replies on every thread (signed `(posted from Claude Code)`, since the reply appears under your account) and resolves it. If it can't resolve a thread, it tells you which ones to resolve on GitHub.
   If you prefer, you can edit the file directly in the GitHub UI or your editor instead. Avoid tagging `@claude` on a thread you've also discussed with Claude Code: that starts a second agent on the same finding.
3. **Wait for the fresh review**, which `/po-review` asks for after it pushes. Check that its summary shows no open findings for you. If you edited the file yourself and the PR has no `review` label, add it to get one.
4. **Accept** by merging the PR, once its checks are green. In solo mode the merge *is* the approval. In team mode, a code owner approves first. Claude never merges for you: a hook blocks it.

What you check at each gate:

- **Intent PR:** the problem is real and the outcome is worth building. *Open questions* is empty, or says `None.`. Merging starts the *Spec from intent* workflow.
- **Spec PR:** every requirement and acceptance criterion is what you want. Each *Policy concern* has a decision: settle it with the policy owner, and pass higher-risk items to the tech lead. Merging hands the change to the engineer.

To regenerate a spec by hand, run `claude`, then `/spec changes/NNNN-<name>`.

**Not your job:** pipeline failures, permissions and workflow bugs. Report them to the platform team, as a GitHub issue labelled `pipeline`.

**Stays with you:** Go or no-go at both gates. Claude flags conflicts but never resolves them.

---

## Engineer

**When:** A spec has been merged.

**What you do**

1. Plan before writing code. Start Claude in plan mode with both artifacts:
   ```
   claude --permission-mode plan
   > Plan changes/NNNN-<name> from its intent.md and spec.md
   ```
   Iterate until you'd be happy implementing the plan yourself, then approve it.
2. Save the plan and commit it first: `> /plan`
3. Implement in a dedicated worktree. You can run two or three of these in parallel:
   ```
   claude --worktree NNNN-<name>
   ```
   For a bug fix (a change with `bug.md`), commit a failing test first, one per acceptance criterion, then lock the tests while Claude fixes the code:
   ```
   SDLC_LOCK_TESTS=1 claude --worktree NNNN-<name>
   ```
4. Verify, then open the PR:
   ```
   make check                       # lint + tests + artifact chain; must exit 0
   > Use the verifier subagent on changes/NNNN-<name>
   gh pr create --fill
   ```
5. Answer the review in Claude Code:
   ```
   > Handle the review findings on PR <N>
   ```
   Claude goes through the findings one at a time and asks what you want. Then it fixes the code, pushes, replies on every thread and resolves it. Tagging `@claude` on a GitHub comment is an optional alternative, where the bot pushes the fix. Use one or the other for a finding, never both: before it pushes, Claude Code checks the branch for bot commits.
   The review runs when the PR opens. To have every later push reviewed too, add the `review` label: it stays on, and each push to the PR is reviewed until you remove it. Claude Code adds it when it pushes fixes.

**Stays with you:** Approving the plan, and deciding the work is done. When Claude makes the same mistake twice, add the correction to `CLAUDE.md`.

---

## Tech lead / architect

**When:** A spec or plan is flagged as higher risk, or the review policy needs changing.

**What you do**

- Review flagged specs and plans: new services, data model changes, security-sensitive work.
- Own `REVIEW.md`: which review passes run, what counts as *Important*, the cap on nits, and what's excluded.
- Watch for findings that keep recurring in review, and move the fix into `CLAUDE.md` or a skill.

**Stays with you:** Approving higher-risk changes, and the review thresholds.

---

## Code owner

**When:** A PR has passed CI and the Claude review.

**What you do**

1. Read the Claude review summary and its inline findings. Every *Important* finding is either fixed or dismissed with a reason, in a reply on its thread. If the PR changed since the review and has no `review` label, add it: that reviews the latest push, and every push after it.
   - **A PR that changes `.github/workflows/claude-*.yml` gets no AI review**, though its check is green. A comment on the PR says so. Review those by hand, with extra care: they control what the agent may do.
2. Check that the diff matches `spec.md` and `plan.md` for its change.
3. **Solo mode:** merge it. The required checks must be green, and nobody can bypass them. If GitHub says the branch is out of date with `main`, click *Update branch* and wait for the checks again: branch protection requires PRs to be up to date, so you see when one is behind. The branch is deleted when it merges. **Team mode:** approve it, then merge. Branch protection requires your approval, and Claude's review never counts as one.

**Stays with you:** The merge decision. The agent opens and updates PRs but can't approve or merge them: the production-gate hook blocks it.

---

## Release manager

**When:** A merged change is ready for production.

**What you do**

```
make deploy-prod RELEASE_AUTHORIZED_BY=<your name>
```

The production gate hook (`.claude/hooks/production-gate.sh`) blocks Claude from running this command, so only a person can. Development deploys (`make deploy-dev`) need no authorization.

**Stays with you:** Authorizing production. The agent can act up to the production gate but can't pass it.

---

## Policy owner

**When:** A policy changes, or a spec raises a concern about your policy.

**What you do**

- Maintain your skill under `.claude/skills/<policy>/SKILL.md`. `security-policy` is the starter example.
- Skills are advisory. A rule that must always hold also needs a hook or a CI check, so ask the platform team for one.
- Help the product owner resolve the concerns that specs flag.

**Stays with you:** What the policy says, and which exceptions are allowed.

---

## Platform team

**When:** You're setting up the pipeline, changing a guardrail, or changing the stack.

**What you own**

| Thing | Where |
|---|---|
| GitHub repo settings (secrets, protection, permissions) | `scripts/bootstrap-github.sh`; re-run it after any change |
| Stack contract (`setup fmt lint test validate check`) | `Makefile`, `.github/actions/setup-stack/` |
| AI tool adapter | `scripts/agent.sh` |
| Build-time guardrails | `.claude/settings.json`, `.claude/hooks/` |
| CI and automation | `.github/workflows/` |
| Agent evals | `evals/`; run with `make evals` |
| Claude's GitHub identity and persona list | `.claude/personas.conf`, `scripts/agent-identity.sh`, `scripts/agent-session.sh`; setup in [agent-identity.md](agent-identity.md) |
| `.gitignore` baseline (node, python) | `templates/gitignore`; `bootstrap-github.sh` adds any missing line, and `make validate` fails on tracked `node_modules` or a branch changing more than 300 files (`SDLC_MAX_CHANGED_FILES`) |

- Before merging a change to `CLAUDE.md`, `.claude/**`, prompts or evals, run the *Agent evals* workflow: Actions → Agent evals → Run workflow. It's on demand for now to save subscription usage. Don't merge a change that lowers the pass rate.
- Turn every production incident into a new task under `evals/tasks/`.
- Hooks and settings are protected from agent edits. Change them through a reviewed PR.

**Stays with you:** The guardrails themselves.

---

## Not built yet

- **Service owner (Maintain stage):** monitoring breaches produce a new `intent.md`. See the roadmap in the [readme](../readme.md).
