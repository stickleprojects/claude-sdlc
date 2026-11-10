# Plan: <short title>

<!-- Stage 3 (Build). Produced in plan mode against intent.md + spec.md, approved by the
engineer before any code is written. -->

Spec: ./spec.md

## Approach

The design in a few sentences, and why it was chosen over alternatives.

<!-- Build or adopt: if the plan builds by hand something a widely used library or framework
provides (routing, state, forms, retries, auth), name it and say why it isn't used: size, a
constraint, or an ADR in docs/adr/. -->

## Steps

Ordered, small steps. Each names the files it touches.

## Verification

- **Definition of done:** <the kinds of work that apply, e.g. Any code, UI>

<!-- The kinds come from templates/definition-of-done.md and the repo's docs/definition-of-done.md.
Name every kind this change is, then show below how each named row is met. A row is a minimum:
anything it asks for that this plan won't do is a descope, under Descopes. -->

Exact commands (normally `make check`) and the expected result for each acceptance criterion,
each driving the criterion at the level it describes (a UI behaviour through the UI).
For bugs: the failing test written and committed first.

## Risks

What could go wrong, and anything needing tech lead or architect approval.

<!-- Check docs/adr/ first. If the plan meets an accepted ADR's "Revisit when" trigger, or makes an
architecture choice no ADR covers (a new framework, service or datastore, or a pattern built by
hand again), add a line: "Architecture decision needed: <question> (ADR NNNN, trigger: <which>)",
or "(no ADR)", followed by what the engineer decided: keep the current architecture, and why; or
raised with the tech lead, who writes or updates the ADR before this plan merges. -->

## Descopes

<None., or each descope and human check, as below>

<!-- .claude/skills/scope.md. Anything this plan leaves undone, untested or unchecked: code under a
tool's exclusion list, a criterion tested below the level it describes, a manual step a test could
do. And anything a person must try by hand because no test can (feel, timing, hardware, the real
game or editor). One entry each, approved by the engineer one at a time, or "None." when there are none:

- Descope: <what> because <reason>. Approved: <name>, <date>.
- Human check: <what to try, and how> because <why a test can't>. Approved: <name>, <date>.

An entry without an Approved: line fails make validate, and the build doesn't start. The verifier
reports each human check as PENDING, and the PR lists them for the owner to try. -->
