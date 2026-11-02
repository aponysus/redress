---
name: legacy-contract-analysis
description: Trace legacy API and calculation outputs through application code and SQL to establish provenance, replication requirements, and migration parity limits.
---

# Legacy contract analysis

Establish what must remain equivalent when reproducing or replacing existing behavior.

## Method

1. Read project instructions and scope the observable contract: entry point, output fields, input parameters, reference version, and relevant environment. Determine whether the task asks for explanation, characterization, or replacement.
2. Trace each requested field through serialization, DTOs, controllers, services, queries/procedures, and source data. Record transformations and source references at each boundary. A database call proves the call and mapping, not unavailable procedure internals.
3. Establish selection predicates, joins and grain, identity, time boundaries/time zones, sign, units/currency, rounding order, null treatment, and grouping where they affect results. Distinguish direct transactions, derived aggregates, and stateful/as-of values.
4. Identify missing definitions or authoritative domain contracts. Label conclusions confirmed, inferred, or unknown where useful. Never reconstruct a formula solely from field names, sample totals, or misleading comments.
5. Propose characterization against a known reference and parity checks using identical inputs and snapshots. Cover boundary dates, empty sets, nulls, duplicates, corrections, and rounding when applicable. Define tolerances only with domain authority; matching a few examples does not prove general equivalence.

## Result and stopping point

Return a field-level provenance table with source location, established semantics, unknown dependency, and proposed comparison. Include the smallest missing-definition list needed to proceed. Stop claims of equivalence at unavailable authoritative logic; continue tracing independent visible portions.

Do not invent SQL or modify production systems. Implementation requires authorization beyond an analysis request; use synthetic fixtures for proposed comparisons.

## Example

A synthetic C# service maps `CashDist` from `sp_GetDistributions`, whose definition is absent. Report the parameters and output mapping. A comment saying “sum amounts” cannot establish eligibility, sign, or as-of logic. Request the procedure definition or another authoritative contract before claiming reproduction.
