---
name: sdlc
description: The pipeline itself, in a project that uses claude-sdlc. Shows which framework version the repo is on and what's new since (breaking changes and optional features first), then updates it with sync-sdlc on a branch and opens the sync PR, working through any merge conflicts and missing make targets with the person. Use when someone says "/sdlc", "update the pipeline", "sync sdlc", "upgrade claude-sdlc", "which version of the pipeline are we on" or "what's new in the framework".
---

# The pipeline: version, what's new, update

The framework's files (skills, hooks, workflows, templates, the `sdlc` CLI) come from claude-sdlc, pulled in by `scripts/sync-sdlc.sh`. This skill keeps a project up to date with it. It never merges the sync PR: a person does that. It's about the framework, not a change: for where a change is and what's next, follow the routing in `.claude/skills/routing.md` (`/next`).

**In the framework repo itself** (its `CLAUDE.md` says `Change tracking: issues`, and `scripts/next-version.sh` exists), there's nothing to sync. Say so, and point at `scripts/next-version.sh --explain` and the release workflow instead.

## 1. Where the repo is

```
cat .sdlc-version        # line 1: <owner/repo>@<ref>, line 2: the commit
```

No `.sdlc-version` means the framework was never synced here: point at the readme's *Getting started* in claude-sdlc and stop.

Find the latest release of that repo (`SDLC_REPO` overrides it, default `stickleprojects/claude-sdlc`):

```
gh api repos/<owner/repo>/releases/latest --jq .tag_name
gh api 'repos/<owner/repo>/releases?per_page=50' --jq '.[] | "\(.tag_name)\t\(.published_at)"'
```

Tell the person in one or two lines: the version they're on (a ref such as `main` is a commit between releases; say which release it's after), the latest release, and how many releases lie between.

## 2. What's new

Read the notes of every release after theirs (`gh api repos/<owner/repo>/releases/tags/<tag> --jq .body`) and summarise them in plain language, in this order:

1. **Breaking changes** (the `⚠ Breaking changes` section): what the project must change, for example a renamed `make` target or a new required artifact section. Check this repo for each one (`grep` the Makefile, `changes/`) and say whether it's affected.
2. **Optional features** (sections titled `Optional: …`): what each one is, that nothing changes until the team adopts it, and how to adopt it. Check whether the repo already uses it, for example whether `docs/adr/` exists for architecture decision records.
3. **Features and fixes:** one line each, only the ones a user of the pipeline would notice.

Then ask with AskUserQuestion: update to the latest release (recommended), to a specific release, to `main` (unreleased, for trying a fix early), or stop.

## 3. Update on a branch

1. **Clean tree first.** The sync refuses uncommitted changes. If `git status --porcelain` shows any, say what they are and ask the person to commit or stash them. Never stash or discard their work yourself.
2. **Branch from the latest main:**
   ```
   git fetch origin && git switch -c chore/sync-sdlc-<version> origin/main
   ```
3. **Sync:** `make sync-sdlc REF=<version>`. In a repo whose Makefile has no `sync-sdlc` target, run `bash scripts/sync-sdlc.sh <version>`.
4. **Read the output and act on each part:**
   - *kept your local changes … merged in*: list the files. These had local edits, and the framework's changes were merged in. Say that their edits survived.
   - *CONFLICT … `<<<<<<<` markers*: go through each file with the person. Show both sides (theirs, then the framework's), explain what each does, recommend one, and ask. Edit the file to the decision, remove the markers, and `git add` it.
   - *CONFLICT … `.sdlc-new`*: the framework's version is beside their file. Merge it by hand the same way, delete the `.sdlc-new` file and `git add` the result.
   - *kept (the framework dropped these…)*: the file is theirs now. Mention it. No action is needed.
   - *your Makefile doesn't define these targets*: the stack-contract ones (`setup fmt lint test validate check new-change status next`) must exist for the pipeline to work. Propose each recipe for this repo's stack, following its existing targets. The optional ones (`coverage`, `evals`, `deploy-dev`, …) only matter for what they name, so ask before adding them.
   - *secrets and variables the workflows use*: the sync checked the GitHub repo by name (values are never readable). No such section means everything is set, or the check was skipped because there's no GitHub `origin` or `gh` isn't logged in. If it was skipped, say so.
     - *MISSING (required)*: the named workflows fail until it's set. Tell the person how (`scripts/bootstrap-github.sh`, or the repo's *Settings → Secrets and variables → Actions*). Never ask for or handle the value yourself. Open the sync PR as a draft until it's set.
     - *ERROR: the agent App is half set up*: spec-from-intent or the Claude review fails at run time. Point at `docs/setup-agent-apps.md` and ask whether to finish setting the App up or remove the parts that are set.
     - *not set (optional)*: one line on what they lose (spec PRs need the *Approve and run workflows* click) and the link. Nothing to do unless they want the App.
     - *not checked*: their `gh` login can't read the names (admin or maintain access is needed). Say it wasn't checked; don't report anything as missing.
5. **Check:** `make check` must exit 0. If it fails because of the new version (say, a new validation rule that existing artifacts break), explain the failure in plain terms and fix the artifacts with the person. Don't edit framework files to make it pass.

## 4. Open the sync PR

Commit what the sync staged, plus the files you resolved, by explicit path (`git diff --cached --name-only` lists them; never `git add -A`). Follow the `agent-identity` skill for the commit trailer and the PR signature.

- **Title:** `chore: sync claude-sdlc <old> → <new>`. If a breaking change needed edits here, use `chore!:` and say so.
- **Body:**
  - the versions from → to, with links to their release notes
  - the breaking changes and what was changed here for each
  - files where local edits were merged, and each conflict with how it was resolved
  - make targets added
  - the secrets and variables report: anything required that's missing (and that the PR is a draft until it's set), a half-set-up App, the optional ones not set, an auto-merge warning (main no longer qualifies; the fix is `scripts/bootstrap-github.sh --mode team`), or that it wasn't checked
  - the optional features in these releases, adopted or not, so the team can decide
  - `make check` passing

Push, open the PR, run `scripts/auto-merge.sh <N>` on it (the `agent-identity` skill), and stop: a person reviews and merges it.

## 5. Afterwards

For each optional feature the repo hasn't adopted, offer in one line to start it, for example drafting proposed ADRs for the decisions this repo has already made, for the tech lead to accept. Don't start one without a yes.
