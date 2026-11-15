# Spec: the whole castle in the data

Intent: ./intent.md

## Summary

Every room of the castle is in the level data, built by rule.

## Requirements

- R1. Every floor of the castle is generated from the floor rules.
- R2. The warp list offers every floor that has a warp point.
- R3. The lift moves between floors in under two seconds.

## Acceptance criteria

- AC1 (R1): a test generates each floor and compares it with the floor rules.
- AC2 (R2): a test lists the warp points and checks the warp list offers each floor.
- AC3 (R3): a test times the lift between the lowest and highest floors.

## Out of scope

None.

## Policy concerns

None.
