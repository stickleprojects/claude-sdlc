---
name: release
description: Release claude-sdlc, starting with a trial sync in a consumer repo. Use when Kieron asks to cut, ship or prepare a release, or to run the consumer trial before one.
---

# Release the framework

For this repo only (#200); the sync never ships it. Consumers found bugs that the tests and evals missed (#182, the Milestone line), so every release is tried in one first: the trial consumer is `stickleprojects/sdlc-sandbox`. Do the steps with Kieron and stop at the first failure.

1. **What's going out.** Run `gh workflow run release.yml` (a dry run) and show Kieron the version and the notes preview from its run summary. Agree with him that `main` is the commit to release.
2. **Sync.** Run `scripts/consumer-trial.sh sync`. It pins `main`'s SHA, makes a fresh clone of the consumer in a new scratch folder (never anyone's working checkout), syncs that SHA with the consumer's own sync script and commits it on `chore/sdlc-trial-<sha>`. It prints the folder. If the sync stops on a conflict, or leaves upgrade steps in `.sdlc/upgrade-pending.md`, work through them in that folder with Kieron, as `/sdlc` would, and commit. Each one is a finding.
3. **Check.** Run `scripts/consumer-trial.sh check <folder>`: `make setup` and `make check` in the consumer.
4. **Real PR.** Run `scripts/consumer-trial.sh pr <folder>`. It opens a draft PR marked do-not-merge. Wait for its CI and Claude review, and read both.
5. **Findings.** Show Kieron what failed or looked wrong. A framework bug gets an issue, and usually a fix before the release. Then run the dry run again, and the trial again from step 2 if `main` changed. Kieron decides whether a finding blocks the release.
6. **Release.** Write the result as one line, starting as `consumer-trial.sh pr` printed it (the PR and the trial's short SHA), then what passed and what didn't, e.g. `stickleprojects/sdlc-sandbox#12 (claude-sdlc 5df79ee): sync clean, make check and CI passed, review found nothing`. The release fails if that SHA isn't the commit it tags: re-run the trial from step 2. Kieron runs `gh workflow run release.yml -f dry_run=false -f trial="<line>"`, or you do once he says to. The release fails without `trial`, and the line goes in the notes under `## Consumer trial`.
7. **Close.** Once the release is out, run `scripts/consumer-trial.sh close <folder>`. It closes the PR, deletes its branch and removes the folder. The consumer upgrades for real through `/sdlc`.
