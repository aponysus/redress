---
name: database-change-safety
description: Plan schema migrations, backfills, stored-procedure changes, and data corrections with preservation, mixed-version compatibility, and recovery checks.
---

# Database change safety

Determine a safe order of changes and how to detect an incomplete or incorrect migration.

## Method

1. Read project instructions, migration tooling, schema, consumers, and the intended data contract. Verify database engine/version and relevant DDL semantics from authoritative sources; transaction and lock behavior differ by engine.
2. Establish preservation invariants and preconditions: key uniqueness, nullability, row eligibility, referential integrity, units, and totals where relevant. Obtain volume and index evidence before estimating lock duration or performance.
3. Check old/new applications against old/new schema. Prefer expand, migrate, then contract when a coordinated one-step change cannot safely preserve compatibility. Include stored-procedure inputs/outputs and readers outside the repository.
4. Design restartable backfills with stable checkpoints, bounded batches, idempotency, and a policy for concurrent writes. Specify reconciliation queries or checks before and after each meaningful transition. Counts alone may hide wrong values or duplicate mappings.
5. State lock/transaction risks and failure recovery. Distinguish reversing schema from restoring lost data; destructive changes may require a verified restore or roll-forward strategy. Do not describe an untested backup as proven recovery.
6. Propose isolated synthetic tests for compatibility, partial progress, reruns, and failed validation. Report observed results only for checks actually executed.

## Result and stopping point

Return migration order, preconditions, validation criteria, and rollback/roll-forward limits. Stop execution if the environment, authority, preservation semantics, or recovery requirements are unresolved. Continue analysis of visible dependencies without guessing production properties.

Never execute destructive SQL, production migrations, or data corrections without explicit authorization for that target and action. This skill provides a method, not database access or permission.

## Example

Adding a required column to a populated synthetic table may need a nullable addition, compatible writers, restartable backfill, reconciliation, and only then a non-null constraint. Dropping the old column before all readers migrate makes application rollback unsafe.
