---
name: documentation-quality-review
description: Assess engineering documentation through bounded reader tasks, clarity, pedagogy, and findability; keep source correctness as a separate review.
---

# Documentation quality review

## Establish the reader and scope

Read applicable project instructions. Use supplied scope and audience when clear;
ask only for missing decisions that affect the review. Identify documentation type,
allowed pages/site, available sources/tools, and whether authoring context is still
present. Prefer a fresh context; disclose any lack of independence. Stay read-only,
including source, tests, configuration, and instructions; do not save a report unless
requested. Behavioral instructions do not enforce tool permissions.

Choose relevant personas: new developer (orientation, definitions, sequence,
examples), maintainer/debugger (entry points, traces, dependencies, operations,
authoritative implementation), architect/modernizer (boundaries, contracts, data
authority, coupling, invariants, lifecycle, failures, unknowns). Judge the path for
the intended reader, without demanding every persona on every page.

## Attempt reader tasks

Inventory the entry page, relevant navigation paths, and a few representative deep
pages. Choose 2–5 realistic tasks spanning comprehension, findability, and action.
For example: explain why a job can remain queued; find the recovery procedure;
determine whether the instructions suffice to retry safely. Include an explicitly
unanswerable task when appropriate to test whether limits are visible.

Attempt each using only documentation. Record the exact navigation/search path,
page/heading, supported answer or inability to answer, and the gap's effect on the
reader. Do not fill gaps from application source, prior agent reports, hidden keys,
or authoring memory. Disclose unavoidable contamination. Search by reader concepts
as well as code symbols; distinguish information absent from information hard to find.

Use those attempts to assess applicable dimensions:

- **Clarity:** explanations rather than names; defined terms, clear referents,
  faithful summaries, no unnecessary jargon.
- **Pedagogy:** prerequisites before details, a usable mental model, illuminating
  examples/counterexamples, an order a newcomer can follow.
- **Findability:** meaningful page names, hierarchy, headings, links, groupings,
  and entry paths that do not require knowing code symbols.
- **Task usefulness:** answerable questions, actionable examples, source pointers,
  contracts, and commands with their verification status.
- **Cognitive load:** proportionate density and granularity; no distracting detail,
  repetition, fragmentation, or abstraction without explanation.
- **Completeness/boundaries:** material assumptions, transitions, dependencies,
  limitations, and edge cases supplied or explicitly unknown; never invent them.
- **Consistency:** terms, navigation, diagrams, equations, prose, and examples agree.

Diátaxis may help diagnose mixed tutorial/how-to/reference/explanation purposes;
it does not require a new directory structure. Avoid style policing or readability
scores. Numerical scores are useful only for controlled comparisons with evidence.

## Separate truth and presentation

A clear page can be false; an accurate page can be unusable. Flag suspicious or
unsupported factual claims for a separate source-grounded pass using existing
investigation/review capabilities. Inspect source only when authorized and available,
after preserving the docs-only task results. For calculations, time semantics,
contracts, and operations retain source-confirmed / inferred / runtime-confirmed /
unresolved distinctions from source-behavior documentation. Runtime-confirmed needs
actual run evidence. Neither implementation nor existing tests proves domain correctness.
Use diagram or rendered-site skills only when relevant and available; text inspection
cannot establish rendering success.

## Finish proportionately

Stop after the bounded sample and tasks, or earlier when missing access prevents
useful assessment. Expand only if a consequential finding needs a nearby page to
resolve it; do not imply site-wide coverage from sampling. Return a brief verdict
for the reader and scope, task outcomes, then a handful of material findings ordered
blocking/significant/minor. For each give location, impacted reader/task, short
evidence, concrete consequence, smallest useful fix, and confidence/access limits.
Distinguish demonstrated failures from plausible concerns and executed checks from
recommendations. Explicitly state if there are no material findings. Leave files
unchanged; a revision pass requires explicit authorization.

An LLM reader simulation is a proxy, not proof of improved human onboarding.
A genuine unfamiliar developer attempting the same task remains valuable validation.
