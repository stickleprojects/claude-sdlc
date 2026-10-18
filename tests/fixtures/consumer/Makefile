# Minimal consumer repo for the scenario tests: the stack contract with a no-op stack.
# Proves the framework works in a repo that isn't Python, without installing anything.

.PHONY: setup fmt lint test validate check exec-bits new-change status

SDLC = PYTHONPATH=tools/sdlc/src python3 -m sdlc.cli

setup fmt lint test:
	@true

validate:
	@$(SDLC) check

check: lint test validate exec-bits

exec-bits:
	@bad=$$(git ls-files -s '*.sh' | awk '$$1 != "100755" {print $$4}'); \
	test -z "$$bad" || { echo "not executable: $$bad"; exit 1; }

new-change:
	@$(SDLC) new $(NAME)

status:
	@$(SDLC) status
