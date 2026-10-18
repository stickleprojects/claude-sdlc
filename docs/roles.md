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

**Stays with you:** Saying what the problem is. If Claude adds something you didn't mean, remove it.

---

## Product owner

**When:** An intent PR or a spec PR asks for your review.

**What you do**

- **Intent PR:** Check that the problem is real and the outcome is worth building. Anything listed under *Open questions* gets answered or removed. Approve and merge to accept. Merging starts the *Spec from intent* workflow, which opens a spec PR.
- **Spec PR:** Check every requirement and acceptance criterion. Each *Policy concern* needs a decision: resolve it with the policy owner, and pass higher-risk items to the tech lead. Approve and merge to accept.
- To regenerate a spec by hand: `claude` → `/spec changes/NNNN-<name>`.

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
   For a bug fix, commit a failing test first, then lock the tests while Claude fixes the code:
   ```
   SDLC_LOCK_TESTS=1 claude --worktree NNNN-<name>
   ```
4. Verify, then open the PR:
   ```
   make check                       # lint + tests + artifact chain; must exit 0
   > Use the verifier subagent on changes/NNNN-<name>
   gh pr create --fill
   ```
5. Answer the review. On any review comment, tag `@claude` to have it push a fix to the branch.

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

1. Read the Claude review summary and its inline findings. Every *Important* finding is either fixed or dismissed with a reason.
2. Check that the diff matches `spec.md` and `plan.md` for its change.
3. Approve. Branch protection requires your approval: Claude's review never counts as one.

**Stays with you:** The merge decision. The agent that wrote the code can't approve it.

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
| Stack contract (`setup fmt lint test validate check`) | `Makefile`, `.github/actions/setup-stack/` |
| AI tool adapter | `scripts/agent.sh` |
| Build-time guardrails | `.claude/settings.json`, `.claude/hooks/` |
| CI and automation | `.github/workflows/` |
| Agent evals | `evals/`; run with `make evals` |

- Before merging a change to `CLAUDE.md`, `.claude/**`, prompts or evals, run the *Agent evals* workflow: Actions → Agent evals → Run workflow. It's on demand for now to save subscription usage. Don't merge a change that lowers the pass rate.
- Turn every production incident into a new task under `evals/tasks/`.
- Hooks and settings are protected from agent edits. Change them through a reviewed PR.

**Stays with you:** The guardrails themselves.

---

## Not built yet

- **Service owner (Maintain stage):** monitoring breaches produce a new `intent.md`. See the roadmap in the [readme](../readme.md).
