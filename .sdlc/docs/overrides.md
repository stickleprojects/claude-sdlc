# Changing the framework for your project: `.sdlc-local/`

The framework lives in `.sdlc/`, and every update rewrites that folder. To change how the
pipeline works in your project, don't edit `.sdlc/`. Put your version in `.sdlc-local/` at the
same path. The sync never writes there, so an update never conflicts with it.

| You want to change | Put it in |
|---|---|
| a template, e.g. the intent's header lines | `.sdlc-local/templates/intent.md` |
| a skill, e.g. an extra step at the end of `/build` | `.sdlc-local/skills/build/SKILL.md` |
| the verifier agent | `.sdlc-local/agents/verifier.md` |
| a prompt the checks use | `.sdlc-local/prompts/<name>.md` |
| the review rules | `.sdlc-local/REVIEW.md`, or add project rules in `docs/review-rules.md` |
| your security policy | `.sdlc-local/skills/security-policy/SKILL.md` (it's yours; the framework ships a placeholder) |
| a hook of your own | a script in `.sdlc-local/hooks/` and a row in `.sdlc-local/hooks/hooks.tsv` |
| make settings, e.g. how to run the tool | `.sdlc-local/local.mk` (e.g. `SDLC = uv run sdlc`) |

Only `skills/`, `agents/`, `templates/`, `prompts/` and `REVIEW.md` can be overridden. The
framework's scripts, its tool and its guardrail hooks can't, because an override there could
switch a guardrail off. You can add hooks, but you can't replace the framework's. Its hooks run
first, and any of them can block a call.

## A whole file

A file in `.sdlc-local/` with no `<!-- extends -->` line replaces the framework's file
completely. That's simplest, but your copy won't pick up the framework's later changes to that
file, and you'll only hear about them when the sync lists your overrides of changed files.

## Only some blocks: `<!-- extends -->`

For a Markdown file, start the override with `<!-- extends -->`. It then holds only the parts it
changes, and the rest still comes from the framework, updates included.

```markdown
<!-- extends -->
Why: our intents name a roadmap milestone (change 0011).

<!-- append: header -->
Milestone: M<n>
<!-- /append -->

<!-- replace: Constraints -->
## Constraints

Godot 4.3 only. Nothing that needs a server.

<!-- /replace -->

<!-- append -->
After the steps above, also run `make godot-import`.
<!-- /append -->
```

- **Blocks:** every heading is a block named by its text (`Constraints`), running to the next
  heading of the same or a higher level, so a `##` block includes its `###` sections. A
  framework file can also mark a finer block with `<!-- block: name -->` and
  `<!-- /block: name -->`; the intent and bug templates mark their `header` lines that way.
  Names ignore case and spacing.
- **Operations:**
  - `replace: <block>` replaces the block, heading included, so write the heading again if you
    want it. An empty replace removes the block. For a marked block, only what's between the
    markers is replaced.
  - `append: <block>` adds text at the end of the block, and `prepend: <block>` adds it just after
    the heading.
  - A bare `append` or `prepend` adds text at the end or start of the whole file. For a skill, a
    bare `append` is the easy way to add "and also …" steps.
- **Order:** operations apply in order, so a later one sees the result of an earlier one.
- **Notes:** text outside the operations is ignored, so use it to say why the override exists.

To see the result, run `.sdlc/scripts/resolve.sh templates/intent.md`. It prints any framework
file with your overrides applied. The skills, the checks, `make new-change` and the review all
read framework files through it.

## When the framework changes

- **`make validate`** resolves every override, and fails when one names a block the framework's
  file no longer has.
- **The sync** lists your overrides of files the update changed, so you can re-read them against
  the new version.

That's the same information a merge conflict used to give, without the conflict.
