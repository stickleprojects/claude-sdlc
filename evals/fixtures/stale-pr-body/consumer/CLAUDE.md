# CLAUDE.md

A small shop's price formatting, built with the claude-sdlc pipeline: changes flow intent.md
(or bug.md) → spec.md → plan.md → code → PR.

## Commands

```
make check   # lint + test + validate; must exit 0 before a PR
make test    # python3 -m unittest
```

## Layout

- `app/prices.py`: formats prices for the checkout page.
- `tests/`: unit tests, one file per module.
