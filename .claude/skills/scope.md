# Scope: silence is not permission

Shared rules for every stage: the plan, build, review and verify steps all follow this file. They exist because agents tend to read a missing rule as permission and a rule's scope as its limit (issue #95).

## Principles

- **Silence is not permission.** Where no rule speaks, do what a careful engineer would expect of this kind of work, not the least that passes the checks.
- **A rule's scope is a minimum, never a limit.** "Every class in `core/` has a test" doesn't mean code outside `core/` goes untested. A tool's exclusion list is for vendored or generated code, not for first-party code that happens to live in the same folder.
- **Agents propose descopes; people decide them.** No agent, worker or reviewer drops scope on its own judgement, and none carries forward a descope that a person hasn't explicitly approved.

## The definition of done

`templates/definition-of-done.md` says what done means for each kind of work (any code, UI, a plugin, a command, data, …), and a repo's own `docs/definition-of-done.md` adds kinds or replaces a row. Each plan names the kinds it is under Verification (`- **Definition of done:** Any code, UI`), and every stage holds the work to those rows. A row is a minimum. Leaving out a kind the change plainly is (a UI change that doesn't name UI), or doing less than a named row asks, is a descope.

## What counts as a descope

Anything the change would leave undone, untested or unchecked that someone would reasonably expect it to cover. It shows up in wording such as "not tested", "not unit-tested", "manual", "by hand", "skipped", "out of scope", "not covered", "later", "follow-up", "TODO", "like the rest of …", or "the rule only covers …". It also shows up without the wording:

- a criterion whose test drives it at a lower level than it describes (see below);
- a step the engineer must do by hand that a test could do;
- first-party code under a lint, format, type-check or coverage exclusion;
- a `skip`, `xfail`, `ignore` or `pragma: no cover` added to new code.

## Recording a descope

A descope is valid only when it's written down with its reason and a person's approval:

- **In a spec:** under **Out of scope**. The product owner approves it by merging the spec PR.
- **In a plan:** an entry under **Descopes**: `- Descope: <what isn't done, tested or checked> because <reason>. Approved: <name>, <date>.` The engineer approves each one explicitly while planning, one at a time, never as part of approving the whole plan. A plan with none says `None.`; `make validate` fails a plan the branch adds or edits whose Descopes is missing, still the template's text, or has an entry without `Approved:`.
- **During a build:** a deviation in build.md (or the PR body for a small build) marked `Engineer decides: yes`. Until the person answers, it is a question, not a decision.

A descope with no `Approved:`, one written in Risks rather than Descopes, or one inherited from an earlier milestone or a neighbouring file ("not tested, like the rest of the dock"), is not approved.

## Human checks

Some things no test can settle: how a game feels, timing, real hardware, a look in the real editor. A check a person must try by hand is a descope of automation, recorded the same way under the plan's **Descopes**: `- Human check: <what to try, and how> because <why a test can't>. Approved: <name>, <date>.` A manual step that a test could do is a plain descope, not a human check. The verifier reports each human check as PENDING, never PASS, and the PR lists them under **To check by hand** for the owner to try before merging.

## Testing at the level the criterion describes

A criterion is tested at the level it is written at. Behaviour a user sees through a UI is tested through that UI (widget, input or end-to-end tests, or inside the real host such as an editor), not only through the model beneath it. A data format is tested with a schema and fixtures. A command is tested by running it. A test file that exists, or a suite that is green, is not evidence that a criterion passes.

## Handing work to a person

When a person reviews or approves anything (a plan, a build plan, a PR, a verifier report), show them first, quoted: the descopes, the risks, the deviations and the open questions. Then the steps or the summary of what was built. Put the parts that need a decision before the parts that don't.
