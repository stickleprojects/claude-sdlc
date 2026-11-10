# Definition of done

<!-- Framework-owned: the sync replaces this file. To change a row for one repo, or add a kind of
work, write docs/definition-of-done.md with the same table (the sync never touches it). A row there
replaces the row here of the same kind, and a new kind is added. Kinds are matched ignoring case.

Each plan says which kinds apply, under Verification: `- **Definition of done:** Any code, UI`.
make validate checks that the plan names them and that each is a kind from one of these tables.
The plan's Verification shows how each row it names is met, the verifier checks each one, and
anything a named row asks for that the change doesn't do is a descope (.claude/skills/scope.md).
A row is a minimum, never a limit. -->

| Kind of work | Done means |
|---|---|
| Any code | New or changed behaviour has tests that fail without the change. Every first-party file is linted, formatted and type-checked; exclusion lists name only vendored or generated code. Coverage per suite doesn't go down. |
| UI | Behaviour a user sees is tested through the UI: widget, input or end-to-end tests that click, type and read what's shown, not only the model beneath it. Text and controls are readable: contrast and size are checked, not only that they exist. |
| Plugin or extension | Tested inside the real host (editor, browser, IDE), loaded the way a user loads it, not only its logic on its own. |
| Command or CLI | A test runs the command as a user would and checks its output and exit code, including a failure. |
| API or service | Tests call it through its real interface and check the contract: status codes, response shape and errors. |
| Data or schema | The format has a schema. Fixtures cover valid and invalid data, and a migration is tested on data in the old shape. |
| Bug fix | A test that reproduces the bug is committed, failing, before the fix. |
| Docs only | Commands and links in the docs are run or checked. No code changes. |
