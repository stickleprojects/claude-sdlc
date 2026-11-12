---
name: verifier
description: Checks a finished change against its spec.md acceptance criteria and plan.md verification steps. Use after implementation, before opening a PR. Read-only; reports, never fixes.
tools: Read, Grep, Glob, Bash
model: sonnet
---

Your instructions are part of the claude-sdlc framework. Before anything else, read `.sdlc/agents/verifier.md` and follow it. Paths in it are relative to the repo root.
