# Minimal consumer repo for the scenario tests: the stack contract with a no-op stack.
# Proves the framework works in a repo that isn't Python, without installing anything.

.PHONY: setup fmt lint test validate check

include .sdlc/sdlc.mk

setup fmt lint test:
	@true

validate:
	@$(SDLC) check

check: lint test validate exec-bits

