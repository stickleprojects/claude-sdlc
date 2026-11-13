# The stack contract. Hooks, CI and evals call ONLY these targets, never language tools
# directly, so switching language means changing this file and
# .github/actions/setup-stack, nothing else.
#
#   setup     install toolchain dependencies
#   fmt       format code; FILES=... limits it to specific files (used by the edit hook)
#   lint      static checks, no changes
#   test      run the test suite
#   validate  check the intent -> spec -> plan artifact chain
#   new-change start a change: make new-change NAME=add-login (TYPE=bug for a bug: bug.md)
#   status    show the stage each change has reached
#   next      each change's next step and the skill that owns it (CHANGE=, REF=origin/main)
#   clauses   a spec as one JSON block per requirement, for the clause check (CHANGE=, REF=)
#   check     everything CI requires; exits non-zero on any failure. A docs-only branch skips
#             `test` (scripts/docs-only.sh, compared with CHECK_BASE); FULL=1 runs everything

.PHONY: setup fmt lint test check-test validate check deploy-dev deploy-prod

# How to run the pipeline's own CLI (Python, via uv). Repos on another stack point this
# at their copy of the tool, e.g. `uv run --project tools/sdlc sdlc`.
SDLC = uv run sdlc
include .sdlc/sdlc.mk

# --- current stack: Python via uv -------------------------------------------------
PY_FILES = $(filter %.py,$(FILES))

setup:
	uv sync

fmt:
ifdef FILES
	@$(if $(PY_FILES),uv run ruff check --fix --quiet $(PY_FILES); uv run ruff format --quiet $(PY_FILES),true)
else
	uv run ruff check --fix .
	uv run ruff format .
endif

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -q

validate:
	$(SDLC) check
# ----------------------------------------------------------------------------------

CHECK_BASE ?= origin/main

check: lint check-test validate exec-bits

# The test suite, unless the branch changes only documentation (#140). FULL=1 always runs it,
# and CI sets FULL on pushes to main, so every commit there is fully tested.
check-test:
	@if [ -z "$(FULL)" ] && why="$$(bash scripts/docs-only.sh $(CHECK_BASE))"; then \
		echo "test: skipped, $$why (FULL=1 runs it)"; \
	else \
		$(MAKE) --no-print-directory test; \
	fi

# Placeholders until there is something to deploy. The production gate hook
# (.sdlc/hooks/production-gate.sh) stops the agent from ever running deploy-prod.
deploy-dev:
	@echo "deploy-dev: nothing to deploy yet"

deploy-prod:
	@test -n "$(RELEASE_AUTHORIZED_BY)" || { echo "deploy-prod needs RELEASE_AUTHORIZED_BY=<release manager>"; exit 1; }
	@echo "deploy-prod: nothing to deploy yet (authorized by $(RELEASE_AUTHORIZED_BY))"
