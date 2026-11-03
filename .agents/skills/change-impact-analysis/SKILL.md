---
name: change-impact-analysis
description: Trace consumers and regression risks before changing shared interfaces, persistence, events, business rules, retries, or configuration.
---

# Change impact analysis

Find the observable boundaries a proposed change could affect.

## Method

1. Read project instructions and define the current contract and intended difference. Establish the relevant version and configuration; distinguish source behavior from deployed behavior.
2. Search direct callers and indirect uses: serialization, generated clients, database queries, event handlers, jobs, configuration, tests, and documentation. Trace representative paths rather than equating text matches with reachable execution.
3. Identify external consumers and dynamic connections that repository search cannot resolve. Separate verified dependencies from suspected ones. Absence of in-repository callers does not establish absence of deployed consumers.
4. Check invariants, compatibility, ordering, failure/recovery, and mixed-version operation where material. Account for migration/deployment order and the limits of rollback.
5. Recommend the smallest safe change boundary and regression checks at affected contracts. Use focused evidence to prioritize consequences rather than listing every imaginable risk.

## Result and stopping point

Return a compact impact map: consumer or boundary, source reference, expected effect, and verification. Add material unknowns and how to resolve them. Stop when the change is bounded or an unavailable consumer prevents a defensible conclusion. Do not claim complete impact coverage from a local search.

Modify code only if the user's task authorizes implementation; this method does not enlarge that scope.

## Example

Renaming a Python attribute also changes a serialized JSON field used by a documented external client. Finding two local callers is insufficient. Preserve a compatibility alias or propose a coordinated migration, and test the wire representation as well as the local callers.
