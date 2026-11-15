# Negotiating a consumer's request with claude-sdlc

This is how a project that uses claude-sdlc (a *consumer*) and the framework agree on a change to the framework's rules. It's written for the AI on either side, and for the person who decides. It works live, with both AIs talking, and offline, with one AI reading only this page.

The framework's stance: **accommodate the consumer, don't capitulate.** A consumer's real need is met. A rule that protects every consumer isn't traded away for one.

## Who does what

- **The consumer's side** speaks for that project's needs.
- **The framework's side** speaks for the framework's invariants and for its other consumers, including ones that don't exist yet.
- **A person decides.** Each repo's owner decides for that repo, and the framework's maintainers decide what the framework ships. Neither AI decides for them. An approval one AI relays from its person isn't an approval for the other side: each side's person confirms in their own session.
- **The rules under negotiation don't change while it runs.** Neither side commits, pushes, opens PRs or issues on the other's repo, or changes the settings, overrides or framework files an item is about. Each project's other work carries on. A new item goes into the exchange.

## What counts as evidence

- **An ask cites something real:** a PR, an issue, a CI run, a log, a review finding, or the minutes lost.
- **A person's instruction counts when it's quoted word for word,** with the date and where it's recorded. It shows what that project needs. On its own it doesn't show what other consumers need.
- **An override the consumer already has in `.sdlc-local/`** is evidence the need is real.
- **A "no" cites the rule and the harm it prevents,** and names the hook, check or test that holds it.
- **A claim nobody has checked is labelled unverified.**
- **Check a fact before stating it as a position:** what a release contains (`git tag --contains <commit>`), what a rule says (its file and line), what enforces it (the hook, check or test). A position built on a wrong fact costs a correction round.

## Accommodate, not capitulate

- **A consumer's need is met through what the framework already offers:**
  - a setting (a repo variable for CI, a `CLAUDE.md` line for skills);
  - a `.sdlc-local/` override;
  - a new opt-in.

  The default is off, CI enforces it, and a test covers it, so other consumers are unaffected.
- **An item that would reach other consumers says what it costs them,** or why it costs them nothing.
- **Invariants aren't traded:**
  - a person merges;
  - no code before a plan;
  - Important review findings block the merge;
  - a descope needs a person's approval;
  - CI and hooks call only `make` targets (the stack contract).
- **When the evidence shows a rule is wrong for everyone, it's a framework fix, not a concession.**

## The output

One proposal, written so the deciding person can read it without technical background. For each item:

1. the ask, and its evidence;
2. the framework's position;
3. the agreed option, or the disagreement, stated fairly from both sides;
4. the cost, including to other consumers;
5. which repo changes, and in what order. Usually that's a framework release first, then the consumer's sync, so nothing is left half-done in either repo;
6. any consumer override to delete once the change ships;
7. what the person must decide.

## How it runs

1. Agree these terms. Either side can propose amendments.
2. Each side lists its items, with the evidence.
3. Each side answers every item on the other's list, in the same round.
4. Repeat until every item is agreed or its disagreement is written down. Stop after about three rounds, and hand what's still open to the person.
5. One side keeps a single transcript of the exchange. If the other side thinks a summary of it is unfair, that summary is replaced by a direct quote.

## Offline

When only one AI is present (someone hands their AI this page and their request), that AI plays its own side honestly and does the following:

- It states the framework's position from this page and the framework's docs. It doesn't assume the answer is yes.
- It writes the same proposal, and marks every framework position as "the framework's stated rule; not confirmed by its maintainers".
- It shows the proposal to its person, who approves it before anything is posted. With that approval, it files the proposal as one issue on the framework's repo, for the maintainers to answer. The issue holds nothing private from the consumer's repo (code, data, names, URLs) beyond what the person approves.

The first negotiation (claude-sdlc and spellbound3d, 14–15 November 2026) ran on these terms. It agreed seven framework changes in about fifteen rounds, all shipped in v0.13.0.
