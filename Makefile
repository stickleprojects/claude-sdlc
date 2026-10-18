# The stack contract. Hooks, CI and evals call ONLY these targets, never language tools
# directly, so switching language means changing this file and
# .github/actions/setup-stack, nothing else.
#
#   setup     install toolchain dependencies
#   fmt       format code; FILES=... limits it to specific files (used by the edit hook)
#   lint      static checks, no changes
#   test      run the test suite
#   validate  check the intent -> spec -> plan artifact chain
#   new-change start a change: make new-change NAME=add-login
#   status    show the stage each change has reached
#   check     everything CI requires; exits non-zero on any failure

.PHONY: setup fmt lint test validate check exec-bits new-change status evals deploy-dev deploy-prod

# How to run the pipeline's own CLI (Python, via uv). Repos on another stack point this
# at their copy of the tool, e.g. `uv run --project tools/sdlc sdlc`.
SDLC = uv run sdlc

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

check: lint test validate exec-bits

new-change:
	@test -n "$(NAME)" || { echo "usage: make new-change NAME=kebab-name"; exit 2; }
	$(SDLC) new $(NAME)

status:
	@$(SDLC) status

# Committed scripts must be executable; a non-executable hook is skipped silently.
exec-bits:
	@bad=$$(git ls-files -s '*.sh' | awk '$$1 != "100755" {print $$4}'); \
	test -z "$$bad" || { echo "not executable in git (git update-index --chmod=+x):"; echo "$$bad"; exit 1; }

evals:
	./evals/run.sh

# Placeholders until there is something to deploy. The production gate hook
# (.claude/hooks/production-gate.sh) stops the agent from ever running deploy-prod.
deploy-dev:
	@echo "deploy-dev: nothing to deploy yet"

deploy-prod:
	@test -n "$(RELEASE_AUTHORIZED_BY)" || { echo "deploy-prod needs RELEASE_AUTHORIZED_BY=<release manager>"; exit 1; }
	@echo "deploy-prod: nothing to deploy yet (authorized by $(RELEASE_AUTHORIZED_BY))"
