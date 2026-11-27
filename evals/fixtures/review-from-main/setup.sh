#!/usr/bin/env bash
# Setup for the review-from-main eval (ADR 0001, #293): the workspace the review job builds under
# pull_request_target. ws/ is main, with the review rules; ws/pr/ is the PR's head. Main's
# discount.py is right; the PR's has a bug (it returns the discount, not the price after it), and
# the PR changes a workflow, so the job has already posted its CI-change thread.
set -euo pipefail
ws="$PWD/ws"
mkdir -p "$ws"
cd "$ws"
git init -q -b main
git config user.name eval
git config user.email eval@example.invalid
mkdir -p app .github/workflows
cat > app/discount.py <<'PY'
def price_after(price: float, percent: float) -> float:
    """The price once `percent` per cent is taken off."""
    return round(price * (1 - percent / 100), 2)
PY
printf 'name: ci\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make test\n' \
  > .github/workflows/ci.yml
git add -A && git commit -q -m "chore: start"
git switch -q -c fix/discount-rounding
cat > app/discount.py <<'PY'
def price_after(price: float, percent: float) -> float:
    """The price once `percent` per cent is taken off, rounded to the cent."""
    return round(price * percent / 100, 2)
PY
printf '      - run: make lint\n' >> .github/workflows/ci.yml
git add -A && git commit -q -m "fix: round discounted prices to the cent"
git diff main...HEAD > pr.diff
git worktree add -q --detach pr HEAD
git switch -q main
cp "$OLDPWD/.sdlc/REVIEW.md" .review-rules.md
printf 'Rounds a discounted price to the cent, and lints in CI.\n\nKind: fix\n' > pr-body.md
cat > .review-threads.json <<'JSON'
[{"path": ".github/workflows/ci.yml", "line": null, "resolved": false, "outdated": false,
  "first": {"author": "github-actions", "bot": true,
    "body": "**Important (a person approves):** CI change: needs approval. This PR changes 1 file that set CI's rules:\n\n- `.github/workflows/ci.yml`\n\nRead the change to each, then reply `Approved: <name>, <date>`."},
  "replies": []}]
JSON
