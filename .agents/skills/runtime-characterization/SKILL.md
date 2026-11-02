---
name: runtime-characterization
description: Design controlled experiments for a runnable reference system, compare observations with source-derived expectations, and establish characterization or parity cases. Use to resolve competing behavioral hypotheses in an authorized test environment, not for unrestricted production probing or ordinary unit test generation.
---

# Runtime characterization

Resolve a specific behavioral uncertainty with experiments whose outcomes
distinguish competing explanations. Design remains useful without live access;
never imply that a proposed experiment was executed.

## Method

1. Establish the target behavior, source-derived expectations, reference build
   or version/commit, database/schema snapshot, configuration, prior state, run
   identity, and execution surface. Confirm the available evidence and scope of
   authorized access. A source checkout and deployed binary may not match. This
   method works with desktop sessions, CLIs, APIs, or database-backed systems;
   it does not assume direct tool access to any of them.
2. Form explicit, distinguishable hypotheses. Choose minimal inputs whose results
   differ under those hypotheses, stating each predicted outcome and its basis.
   If all candidate implementations predict the same result, choose a better
   case. Do not substitute a collection of happy-path examples for discrimination.
3. Prefer synthetic or explicitly approved non-sensitive fixtures. Specify frozen
   inputs, preconditions, parameters, relevant configuration, reset/recovery
   conditions, and permitted side effects. Account for state changes between
   runs. Identify how observations will be captured before proposing execution.
4. Choose relevant boundaries proportionately: dates and inclusivity, zero or
   missing data, negatives, nulls, duplicates, aggregation, sign, rounding,
   repeated execution, corrections, prior state, partial failure, restart, and
   ordering. Use `test-design` when available to refine cases and oracle limits.
5. For actual runs or supplied results, associate expected and observed outputs,
   logs/traces, warnings/errors, run result, and environment constraints with
   the version, fixture, and run identity. Preserve evidence only in approved
   storage. Do not export customer data, credentials, or sensitive payloads into
   public documentation, fixtures, logs, or tool telemetry.
6. Compare observations with source-derived statements and previous reference
   runs. Mark behavior runtime-confirmed only for the tested version,
   configuration, state, and input. Record contradictions in the affected page
   and investigate version/configuration differences before generalizing. An
   absent log or inconclusive outcome is not proof that a path never executed.
7. Prefer executable characterization tests and stable reference outputs when
   practical and within the requested implementation scope. Specify comparison
   rules for decimals, currency, ordering, timestamps, and nondeterminism. Justify
   tolerances from the contract or measurement properties before comparing;
   never relax them merely to make parity pass.
8. Separate behavioral equivalence from independent domain correctness. Matching
   a reference can reproduce its defects. When results conflict with an
   authoritative domain specification, document the disagreement and preserve
   that distinction in tests and the maintained explanation.

## Result and stopping point

Return either a concise experiment specification or an evidence-grounded
comparison of actual results, plus suggested narrow updates to the same
maintained documentation. Include hypotheses, discriminating cases, predicted
outcomes, capture/comparison rules, and unresolved evidence as appropriate.
Stop when the targeted uncertainty is resolved, the available result is
inconclusive with a stated next observation, or further work needs a new
authorization or data decision. Do not create a mandatory experiment database.

The skill grants no environment access or execution authority. Do not connect
to sensitive systems, submit jobs, change production data, or run destructive
commands without explicit task authorization covering the target and action
and applicable organizational controls. Existing authorization need not be
requested again. Without it, provide the experiment design. Do not create a
remote desktop driver, export mechanism, or test harness merely to use this skill.

## Example

For a fictional integer counter, compare `[start, end)` against `[start, end]`.
With events `(10, 100)` and `(20, 250)` and a window from 10 to 20, the hypotheses
predict 100 and 350 respectively. Freeze the fixture and reference build, record
the actual output if an authorized run occurs, and document which hypothesis
it supports. Observing 350 would characterize that run; it would not establish
that end-inclusive behavior is correct under a separate half-open contract.
