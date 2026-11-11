# Spec: Search the role list

Intent: ./intent.md

## Summary

A text box above the role list filters it as the user types.

## Requirements

- R1. The role list has a search box. Typing in it filters the list to roles whose title contains the text, ignoring case.
- R2. When no roles match the search, the list shows the message "No roles match", offers a button that clears the search, and keeps the text in the search box.

## Acceptance criteria

- AC1 (R1): through the UI, typing "ENGINEER" in the search box leaves only the fixture roles whose title contains "engineer".
- AC2 (R2): through the UI, typing "zzz" shows "No roles match", and the search box still holds "zzz".

## Policy concerns

None.

## Out of scope

Searching anything but the title.
