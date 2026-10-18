#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit): format the edited file through the stack contract
# (`make fmt FILES=...`), so this hook works whatever language the repo uses.
# Fast and file-scoped on purpose; full lint and tests run in `make check` and CI.
set -uo pipefail

path="$(jq -r '.tool_input.file_path // empty')"
[[ -z "$path" || ! -f "$path" ]] && exit 0
cd "${CLAUDE_PROJECT_DIR:-$PWD}" || exit 0
make -s fmt FILES="$path" >/dev/null 2>&1 || true
exit 0
