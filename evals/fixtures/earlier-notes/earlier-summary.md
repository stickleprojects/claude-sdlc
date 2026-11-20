**Review of #31** (CSV export)

- Findings: 0 Important, 0 Nit.
- Notes:
  - The PR body says rows are semicolon-separated, but `app/export.py` writes commas. Update the body to match the code.
  - CHANGELOG.md has no entry for the export, and CLAUDE.md asks for one in every `feat:` PR. Add a line.
  - The product owner's approval is needed before this merges: the export adds a download users will see.
- Compared the diff with the PR body.

Findings are comments and threads only. This review doesn't approve the PR, and a human merges it.

<!-- review-findings: important=0 nit=0 -->
