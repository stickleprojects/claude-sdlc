# claude-sdlc's make targets (#133). A project's Makefile has `include .sdlc/sdlc.mk` and
# keeps only the stack contract: setup fmt lint test validate check (validate runs
# `$(SDLC) check`). Everything below arrives with the sync, so a new framework target never
# means editing the project's Makefile.
#
# Settings go in .sdlc-local/local.mk (never synced), or before the include line:
#   SDLC   how to run the pipeline's tool (default: python3 with PYTHONPATH=.sdlc/src;
#          a Python project might use `uv run sdlc` instead)

-include .sdlc-local/local.mk
SDLC ?= PYTHONPATH=.sdlc/src python3 -m sdlc.cli

# Including this file mustn't change the project's default target.
_sdlc_default_goal := $(.DEFAULT_GOAL)

.PHONY: new-change status next clauses exec-bits evals sync-sdlc

# Start a change: make new-change NAME=add-login (TYPE=bug for a bug: bug.md).
new-change:
	@test -n "$(NAME)" || { echo "usage: make new-change NAME=kebab-name [TYPE=bug]"; exit 2; }
	@$(SDLC) new $(NAME)

# The stage each change has reached.
status:
	@$(SDLC) status

# Each change's next step and the skill that owns it; the entry skills route by it.
# CHANGE=0002 limits it to one change, REF=origin/main reads what's merged.
next:
	@$(SDLC) next $(CHANGE) $(if $(REF),--ref $(REF))

# One block per requirement (its text, the criteria and plan lines citing it), read by
# .sdlc/scripts/clause-check.sh. CHANGE=0002 is required; REF=origin/main keeps only what changed.
clauses:
	@test -n "$(CHANGE)" || { echo "usage: make clauses CHANGE=0002 [REF=origin/main]"; exit 2; }
	@$(SDLC) clauses $(CHANGE) $(if $(REF),--ref $(REF))

# Committed scripts must be executable; a non-executable hook is skipped silently.
exec-bits:
	@bad=$$(git ls-files -s '*.sh' | awk '$$1 != "100755" {print $$4}'); \
	test -z "$$bad" || { echo "not executable in git (git update-index --chmod=+x):"; echo "$$bad"; exit 1; }

# The agent evals (they call the model). EVAL_TASKS_DIR and EVAL_MIN_PASS_RATE: see the script.
evals:
	./.sdlc/evals/run.sh

# Update the pipeline: make sync-sdlc [REF=v0.11.0]
sync-sdlc:
	.sdlc/scripts/sync-sdlc.sh $(REF)

.DEFAULT_GOAL := $(_sdlc_default_goal)
