---
name: build
model: sonnet
effort: medium
description: Stage 3 (Build), after /plan. Build a change from its merged plan.md. A small plan is built straight away in one session; a larger one first gets a build plan (build.md) that the person approves as a file, then one milestone per session. Checks that the previous session finished (committed, pushed, tests passing) before doing more. "/build all" runs every remaining milestone in turn, each in a fresh subagent, through to the PR. Use when someone says "/build", "/build 0001", "/build all", "start the build", "continue the build", "next build step" or "build the rest".
---

This skill is part of the claude-sdlc framework. Read `.sdlc/skills/build/SKILL.md` and follow it. Paths in it are relative to the repo root.
