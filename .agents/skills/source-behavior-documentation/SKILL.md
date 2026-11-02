---
name: source-behavior-documentation
description: Reconstruct an undocumented subsystem from repository source to write grounded architecture, execution-flow, domain, or calculation documentation. Use for multi-pass investigation and maintained documentation, not ordinary prose cleanup or a quick symbol explanation.
---

# Source behavior documentation

Build a useful explanation one source-grounded slice at a time. Use
`repository-onboarding` for the repository map and development context;
`legacy-contract-analysis` for detailed field, calculation, or SQL provenance.
This method connects those investigations to maintained documentation for humans.

## Method

1. Establish the requested subsystem, question, and allowed write scope. Confirm
   actual source access, read applicable project instructions and existing docs,
   and identify the source revision when possible, including relevant local
   changes. Separate repository facts from deployment facts. Do not silently
   expand the task to unrelated systems.
2. Reconnoiter breadth-first. Locate relevant solutions, projects, packages,
   framework/platform constraints, API/UI/job/service entry points, orchestration,
   persistence, configuration, external calls, domain entities, tests, and docs.
   Sample representative paths guided by source; do not read every file simply
   to claim completeness. Prioritize deeper slices by usefulness and uncertainty.
3. Trace one meaningful execution path or output depth-first, including its
   consumers, models/DTOs, service code, queries/procedures, state or materialized
   results, and configuration. Follow values back to their authority. Distinguish
   retrieval, transformation, aggregation, original computation, and persistence;
   a method that retrieves a value need not calculate it.
4. Establish consequential semantics where relevant: input/output grain and
   identity; effective, valuation, posting, and as-of time; inclusive/exclusive
   boundaries; currency/units, precision, rounding order, sign, nulls/defaults,
   conditional branches, transaction categories, and prior-run dependencies.
   Include caching, concurrency, failures, transactions, and restart behavior
   when they affect the explanation. Omit dimensions that do not apply.
5. Separate source-confirmed statements from inference, runtime observations,
   and unresolved questions using the evidence rules below. Resolve conflicts
   between comments, tests, and implementation explicitly. An unavailable
   stored procedure establishes a boundary, not permission to guess its formula.
6. When documentation is requested, update the existing authoritative pages in
   the target repository. Organize around readers' navigation, responsibilities,
   flows, contracts, and useful operations. Reference consequential assertions
   with repository-relative paths and symbols, a baseline source revision, and
   line references where helpful. Prefer stable paths/symbols over bare line
   numbers. Use relative document links and small diagrams or mathematics only
   for relationships or derivations the evidence establishes.
7. Finish a coherent bounded section once important claims are traceable and
   limitations explicit. If authority is missing, state what definition, contract,
   or controlled observation would settle the question. Continue independent
   visible paths when useful; do not fill the gap with a plausible formula.

## Evidence rules

- **Source-confirmed:** inspected implementation or an authoritative contract
  establishes the statement at the identified revision. State which authority.
- **Inferred:** a narrowly stated interpretation remains unproven; explain why.
- **Runtime-confirmed:** a documented run establishes an observation only for
  its tested version, configuration, state, and inputs. Use this label only when
  such evidence exists; source inspection alone cannot supply it.
- **Unresolved:** necessary evidence is absent or contradictory; name the gap.

Implementation, observed deployment behavior, and independently validated domain
correctness are different claims. A test may preserve a defect, a deployment may
differ from the checkout, and agreement between outputs does not prove correctness.

## Result and stopping point

For reconnaissance, return a short source-grounded map, prioritized deeper
slices, actual unknowns, and a suggested first slice in chat or approved temporary
storage. For an explicit documentation request, write a coherent set of navigable
pages in the authorized target location. Do not automatically produce both or
generate empty architecture, domain, calculation, and verification pages.

Reuse the target's documentation conventions. Keep temporary investigation notes
outside the repository unless requested. Do not create a parallel claims register
or turn `../../../AGENTS.md` into an architecture encyclopedia. Documentation-only work
does not authorize production-code edits or rewriting project instructions.
Keep sensitive findings and source in approved project locations; do not copy
proprietary excerpts into a public toolkit, external report, or unrelated output.

## Example

A fictional service maps `CashDist` from an unavailable `sp_GetDistributions`.
Document the entry point, parameters, mapping, and consumers with source
references. Describe the value as retrieved at this boundary; its original
calculation remains unresolved. A comment saying “sum amounts” cannot establish
eligibility, time treatment, signs, or rounding. Name the missing procedure or
authoritative contract needed for a calculation page.
