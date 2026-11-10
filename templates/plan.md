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

Exact commands (normally `make check`) and the expected result for each acceptance criterion,
each driving the criterion at the level it describes (a UI behaviour through the UI).
For bugs: the failing test written and committed first.

## Risks

What could go wrong, and anything needing tech lead or architect approval.

<!-- Descopes (.claude/skills/scope.md): anything this plan leaves undone, untested or unchecked,
including manual steps a test could do and new code under a tool's exclusion list. One line each,
approved by the engineer one at a time: "Descope: <what> because <reason>. Approved: <name>, <date>."
A descope without an Approved: line blocks the build. -->

<!-- Check docs/adr/ first. If the plan meets an accepted ADR's "Revisit when" trigger, or makes an
architecture choice no ADR covers (a new framework, service or datastore, or a pattern built by
hand again), add a line: "Architecture decision needed: <question> (ADR NNNN, trigger: <which>)",
or "(no ADR)", followed by what the engineer decided: keep the current architecture, and why; or
raised with the tech lead, who writes or updates the ADR before this plan merges. -->
