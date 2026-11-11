# Spec: Floor mode

Intent: ./intent.md

## Summary

The editor dock gets a floor mode for laying out a whole floor at once.

## Requirements

- R1. The dock has a floor mode. Choosing a floor generates a 3D scene with every room on it, opened in the editor, with doorways drawn between neighbouring rooms.
- R2. A room moved by hand snaps to a grid cell.

## Acceptance criteria

- AC1 (R1): headless, `place_rooms` for a floor of three rooms returns three rooms one grid cell apart.
- AC2 (R2): headless, `move_room` to (5, 7) puts the room at (4, 8).

## Policy concerns

None.

## Out of scope

Editing doorways by hand.
