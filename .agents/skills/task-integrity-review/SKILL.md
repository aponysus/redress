---
name: task-integrity-review
description: Review a change or completion claim against the original engineering outcome to detect narrowed behavior, weakened verification, and unsupported evidence. Use for consequential code, configuration, tests, or source-grounded documentation reviews, not routine style cleanup.
---

# Task integrity review

Use in ordinary Agent mode or alongside Architect, Systems Investigator, Test
Engineer, or Documentation Reviewer. Assess observable outcomes and evidence,
without attributing intent. Scale the review to the task's risk.

## Method

1. Read applicable project instructions and the original request or authoritative
   task description, not only the implementer's summary. Recover the purpose,
   specified behavior, critical invariants, allowed edits, and evidence that would
   distinguish success from a shortcut. If original requirements are unavailable,
   say so and review only supported claims; ask when missing authority blocks a
   consequential judgment.
2. Establish the supplied diff, revision, or commit range. Inspect affected
   implementation, tests, docs, scripts, CI/configuration, and consumers, including
   unexpected changes outside scope. Disclose a missing baseline or diff rather
   than inventing a comparison.
3. Look for relevant discrepancies: removed or weakened assertions, skipped
   checks, broad mocks, fixture-specific constants, special-cased inputs, narrowed
   behavior, suppressed errors/warnings, altered benchmarks or acceptance
   conditions, and artifacts that fail the user's or reader's task.
4. Challenge the evidence. Were tests derived from requirements or merely the
   modified implementation? Do run records establish claimed execution, and do
   citations support the actual claim? Are baselines and runtime experiments
   representative? Compare visible success with independent expectations;
   generated output is not independent verification of itself. Separate
   source-confirmed facts, inference, runtime observations, and unresolved gaps.
5. When permitted, use targeted nondestructive checks with independent contract
   examples, invariants, and boundaries. Report exact commands and observed
   results. Never rewrite production or verification artifacts during this
   read-only review. If execution is unavailable, name a concrete discriminating
   check and mark it unrun; do not imply tools or environments were available.
6. Distinguish a legitimate correction from verification gaming. A changed or
   deleted test is not itself a defect. Establish why the old expectation was
   wrong, which authoritative contract supersedes it, and whether the correction
   was in scope. Flag unsupported changes to the verification contract, not every
   disagreement with legacy tests.

For docs and diagrams, distinguish semantic accuracy from reader usability and
rendering. Trace consequential behavioral claims to source when authorized;
missing SQL definitions or runtime evidence remain gaps. Use
`documentation-quality-review` for reader tasks and diagram/rendered review skills
when relevant and available; preserve any docs-only assessment separately.

## Boundaries and result

Stay read-only unless the user separately authorizes edits. Do not silently save
a durable report or checklist. These instructions do not enforce tool permissions.
Prefer a fresh independent session; changing persona in a shared conversation does
not establish independence. For high-impact changes, recommend authoritative
acceptance tests, protected CI, reference results, or human/domain review outside
the implementer's control. The toolkit cannot guarantee those controls.

Return at most a handful of supported findings ordered by impact. For each give
an exact path/symbol or passage, evidence, violated purpose or invariant, concrete
consequence, confidence, and smallest corrective action. Distinguish demonstrated
discrepancies, credible concerns, and unassessed areas. Include the inspected scope,
checks actually performed, and material limitations, separately from proposed or
blocked checks. Stop when the bounded task is assessed or missing evidence prevents
further useful review. If no material finding is supported, say so briefly; this
is not proof of overall correctness. Avoid speculative accusations and universal
checklists.

## Example

A fictional account summary must refresh when line items change while reusing
cached totals for identical inputs. A patch special-cases the visible account or
changes an expected value to bless a stale total. Compare the original request
with the diff, then check fresh inputs, changed records under the same account,
and another account. Verify cache reuse with an observable calculation count,
not timing. Removing caching can fix the stale value while still violating the
task. A changed assertion is justified only if independent contract evidence shows
the previous expectation was wrong.
