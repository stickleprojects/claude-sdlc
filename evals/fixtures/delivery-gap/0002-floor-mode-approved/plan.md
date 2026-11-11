# Plan: Floor mode

Spec: ./spec.md

## Approach

`evals/fixtures/delivery-gap/code/floor_model.py` builds every room on a floor (R1) and snaps
moved rooms to the grid (R2). `evals/fixtures/delivery-gap/code/dock.py` adds the dock's floor
mode: choosing a floor shows it in the floor tab, and dragging a room there moves it.

## Steps

1. Place a floor's rooms and draw them in the dock (AC1).
2. Snap moved rooms to the grid (AC2).

## Verification

| Criterion | Command | Expected |
|---|---|---|
| AC1 | `make test` (`test_floor_model.py::test_place_rooms`) | three rooms, one cell apart |
| AC2 | `make test` (`test_floor_model.py::test_move_snaps`) | (4, 8) |

- **Definition of done:** Any code, UI

## Descopes

- Descope: R1's 3D scene opened in the editor; this change shows the floor as a 2D diagram in the dock (boxes and doorway lines) because the scene builder lands in change 0010. Approved: Sam, 2026-11-01.

## Risks

None.
