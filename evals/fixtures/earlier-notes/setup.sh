#!/usr/bin/env bash
# Setup for the earlier-notes eval (#242): a PR repo in ./notes whose first commit is the one an
# earlier review saw. Its summary had three notes. Since then the PR body was fixed (no
# commit), a commit added the CHANGELOG line, and nobody has approved. The workflow's files
# are written as it writes them: .review-earlier-summary.md (that summary and the PR's
# commits) and .review-threads.json (no threads).
set -euo pipefail
src="evals/fixtures/earlier-notes"
mkdir -p notes/app
cd notes
git init -q -b main
git config user.name eval
git config user.email eval@example.invalid
cp "../$src/CLAUDE.md" CLAUDE.md
git add -A && git commit -q -m "chore: start"
git switch -q -c feat/csv-export
cp "../$src/export.py" app/export.py
git add -A && git commit -q -m "feat: CSV export of orders"
printf '# Changelog\n\n- CSV export of orders for the download button.\n' > CHANGELOG.md
git add -A && git commit -q -m "docs: changelog entry for the CSV export"
cp "../$src/pr-body.md" pr-body.md
echo '[]' > .review-threads.json
{
  echo "# The summary this review replaces"
  echo
  echo "Last edited: $(git log -1 --format=%cI HEAD~1)"
  echo
  cat "../$src/earlier-summary.md"
  echo
  echo "# The PR's commits, oldest first"
  echo
  git log --reverse --format='%h %cI %s' main..HEAD
} > .review-earlier-summary.md
