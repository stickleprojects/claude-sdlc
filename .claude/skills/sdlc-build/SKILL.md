---
name: sdlc-build
model: sonnet
effort: medium
description: Stage 3 (Build), after /sdlc-plan. Build a change from its merged plan.md. A small plan is built straight away in one session; a larger one first gets a build plan (build.md) that the person approves as a file, then one milestone per session. Checks that the previous session finished (committed, pushed, tests passing) before doing more. "/sdlc-build all" runs every remaining milestone in turn, each in a fresh subagent, through to the PR. Use when someone says "/sdlc-build", "/sdlc-build 0001", "/sdlc-build all", "start the build", "continue the build", "next build step" or "build the rest".
---

This skill is part of the claude-sdlc framework. Run `.sdlc/scripts/resolve.sh skills/build/SKILL.md` and follow what it prints: the skill with this project's overrides (in .sdlc-local/) applied. Read any other file under .sdlc/ that it names the same way, with resolve.sh. Paths are relative to the repo root.
