<!-- The frontmatter for this skill is in .claude/skills/security-policy/SKILL.md, which Claude Code reads. -->

# Security policy (starter set: replace with your organisation's)

- Secrets never go in the repo, in logs or in prompts. Code reads them from the environment at runtime.
- Every external input is validated at the boundary it enters through.
- A new third-party dependency needs a stated reason in the spec and a pinned version.
- Personal data is collected only when a requirement names it, and the spec says how long it is kept.

Skills are advisory. A rule that must always hold also needs a hook (`.sdlc/hooks/`) or a CI check behind it. Note in the spec which rules have no such enforcement yet.
