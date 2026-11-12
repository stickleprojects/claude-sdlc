---
name: plan
description: Stage 3 (Build), before /build. Plan a change whose spec is merged, in plan mode, then save the approved plan as changes/<slug>/plan.md and open its PR. Works out which change to plan (asks when several are ready); on a change already planned, asks whether to replace the plan or build it; with nothing to plan, offers what comes before. Use when someone says "/plan", "/plan 0002", "plan the next change" or "save the plan".
---

This skill is part of the claude-sdlc framework. Run `.sdlc/scripts/resolve.sh skills/plan/SKILL.md` and follow what it prints: the skill with this project's overrides (in .sdlc-local/) applied. Read any other file under .sdlc/ that it names the same way, with resolve.sh. Paths are relative to the repo root.
