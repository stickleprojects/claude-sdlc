#!/usr/bin/env bash
# Print a framework file with the project's override applied (#133).
#
# Usage: .sdlc/scripts/resolve.sh <path under .sdlc/>    e.g. skills/build/SKILL.md
#
# The skill and agent stubs, the review workflow and the checks read framework files through
# this, so a project's .sdlc-local/<path> (a whole file, or `<!-- extends -->` blocks) wins.
# Needs only python3: the tool runs from .sdlc/src, as `make validate` does in any stack.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHONPATH="$root/.sdlc/src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m sdlc.cli --root "$root" resolve "$@"
