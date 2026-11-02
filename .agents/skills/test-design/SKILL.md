---
name: test-design
description: Derive meaningful test oracles and minimal adversarial cases for new behavior, regressions, refactors, calculations, concurrency, or compatibility.
---

# Test design

Choose tests that protect required behavior rather than mirror the implementation.

## Method

1. Read project instructions, requirements, and public contracts. Establish the observable outcomes and invariants before treating code or existing assertions as an oracle. Resolve conflicting authorities explicitly.
2. Identify states, transitions, boundaries, and failure outcomes. Prioritize scenarios by consequence and reachability; include cancellation, retries, partial success, and resource ownership only where relevant.
3. Inspect existing tests for overlap and gaps. Characterization tests describe current behavior; they do not establish that it is desired. Differential tests require an independently justified reference and shared semantics.
4. Choose the cheapest level that exercises the relevant boundary: unit, integration, contract, property, characterization, or differential. Specify deterministic data, controlled time/randomness, and synchronization rather than sleep-based concurrency guesses.
5. For each proposed case, give the triggering input/state, exact expected result or property, its authority, and what failure it detects. Identify environment dependencies and unresolved oracle questions.

## Result and stopping point

Return a prioritized set of distinct cases. If expected behavior is unresolved, explain the decision needed instead of encoding a guess. Stop when material contracts and reachable failure modes are covered; do not pad the suite with implementation-shaped checks.

Implement tests only when requested, within scoped tests/fixtures/helpers. Do not alter production behavior, dependencies, or settings to make tests pass. Report executed commands and actual results separately from proposals.

## Example

A fictional contract defines a reporting window as `[start, end)`, while an existing test includes an event exactly at `end`. Derive cases at both boundaries from the contract and flag the disagreement. Copying the existing assertion would preserve the defect rather than test the requirement.
