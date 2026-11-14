# Spec: Thor's height and rig in the docs

Intent: ./intent.md

## Summary

Thor moves to the large rig at 3.0 units, and the docs that describe him say so.

## Requirements

- R1. The docs match the new Thor: the art bible's characters line gives Thor at 3.0 units on the large Barbarian with `Rig_Large` clips and `Flexing` for interact; `docs/gdd/characters.md` gives his height as 3.0; `docs/architecture.md` shows the per-rig animation libraries.
- R2. Thor's look names `Rig_Large`, and when a look names a rig that `looks.json` doesn't define, loading fails with an error that names the character.

## Acceptance criteria

- AC1 (R1): a search of the art bible's characters line finds `Thor`, `3.0`, `Rig_Large` and `Flexing`; a search of `docs/gdd/characters.md` finds Thor's row with `3.0`; a search of `docs/architecture.md` finds `Rig_Large` in its section on animation libraries.
- AC2 (R2): a test loads Thor's look and finds `rig: Rig_Large`.

## Policy concerns

None.
