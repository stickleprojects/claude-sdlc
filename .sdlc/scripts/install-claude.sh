#!/usr/bin/env bash
# Install Claude Code for one CI job, inside the job's own temp folder (#136). Never globally:
# a self-hosted runner keeps its home between jobs, so a global install collides with the
# `claude` that claude-code-action leaves in ~/.local/bin, leaks into other repos' jobs and
# keeps whatever version got there first.
#
# Usage: bin="$(.sdlc/scripts/install-claude.sh)"
#   Installs @anthropic-ai/claude-code@$CLAUDE_CODE_VERSION into $RUNNER_TEMP/claude-code
#   and prints the folder holding `claude`. In a workflow it also adds that folder to
#   $GITHUB_PATH, so later steps find it first. In the same step, put it on PATH yourself:
#     PATH="$bin:$PATH" .sdlc/scripts/agent.sh ...
#   npm's output goes to stderr, so stdout is only the folder.
#
# Env:
#   CLAUDE_CODE_VERSION  the version to install (default: the version below)
#   RUNNER_TEMP          where to install (set by GitHub Actions; a new temp folder otherwise)
set -euo pipefail

version="${CLAUDE_CODE_VERSION:-2.1.322}"
prefix="${RUNNER_TEMP:-$(mktemp -d)}/claude-code"

npm install --prefix "$prefix" --no-fund --no-audit --no-save \
  "@anthropic-ai/claude-code@$version" >&2
bin="$prefix/node_modules/.bin"
if [[ ! -x "$bin/claude" ]]; then
  echo "install-claude.sh: no claude in $bin after the install" >&2
  exit 1
fi
if [[ -n "${GITHUB_PATH:-}" ]]; then echo "$bin" >> "$GITHUB_PATH"; fi
echo "$bin"
