---
name: sdlc
description: The pipeline itself, in a project that uses claude-sdlc. Shows which framework version the repo is on and what's new since (breaking changes and optional features first), then updates it with sync-sdlc on a branch and opens the sync PR, working through any merge conflicts and missing make targets with the person. Use when someone says "/sdlc", "update the pipeline", "sync sdlc", "upgrade claude-sdlc", "which version of the pipeline are we on" or "what's new in the framework".
---

This skill is part of the claude-sdlc framework. Run `.sdlc/scripts/resolve.sh skills/sdlc/SKILL.md` and follow what it prints: the skill with this project's overrides (in .sdlc-local/) applied. Read any other file under .sdlc/ that it names the same way, with resolve.sh. Paths are relative to the repo root.
