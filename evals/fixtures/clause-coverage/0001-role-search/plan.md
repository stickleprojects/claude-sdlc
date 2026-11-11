# Plan: Search the role list

Spec: ./spec.md

## Approach

A search box above the list filters the rendered roles on each keystroke, matching the title
ignoring case (R1, AC1). When nothing matches, the list area shows "No roles match" and the box
keeps its text (AC2).

## Steps

1. Add the search box and the title filter (AC1).
2. Show "No roles match" for an empty result, leaving the box's text alone (AC2).

## Verification

| Criterion | Command | Expected |
|---|---|---|
| AC1 | `make test` (`tests/ui/test_search.py::test_filters_by_title`) | only titles containing "engineer" remain |
| AC2 | `make test` (`tests/ui/test_search.py::test_no_match_message`) | "No roles match" shows and the box holds "zzz" |

- **Definition of done:** Any code, UI

## Descopes

None.

## Risks

None.
