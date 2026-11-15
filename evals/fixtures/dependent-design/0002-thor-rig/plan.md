# Plan: Thor's height and rig in the docs

Spec: ./spec.md

## Approach

Thor stays on the medium rig at 2.4 units, so no animation libraries change. Only the docs are touched: the art bible's characters line is edited by hand, and nothing in the game's code or scenes changes.

## Steps

1. Edit the art bible's characters line for Thor.
2. Add a search test for AC1.

## Verification

| Criterion | How it's checked |
|---|---|
| AC1 | `tests/test_docs.py::test_thor_line` searches the characters line |
| AC2 | `tests/test_looks.py::test_thor_rig` loads Thor's look |

## Descopes

None.

## Risks

None.
