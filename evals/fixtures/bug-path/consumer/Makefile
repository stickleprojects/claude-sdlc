# A small consumer for the bug-path evals (#160): a stdlib-only Python app with one bug, so
# `make check` is quick and needs nothing installed.

.PHONY: setup fmt lint test validate check

include .sdlc/sdlc.mk

setup fmt lint:
	@true

test:
	@python3 -m unittest discover -s tests -q

validate:
	@$(SDLC) check

check: lint test validate exec-bits
