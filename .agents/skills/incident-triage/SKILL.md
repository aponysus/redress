---
name: incident-triage
description: Investigate observed runtime failures, latency, stuck jobs, retry storms, or inconsistent results using evidence and discriminating hypotheses.
---

# Incident triage

Find the next observation that most efficiently distinguishes causes and informs safe recovery.

## Method

1. Read project instructions and establish exact symptoms, affected operations/users, time range/time zone, and current impact. Distinguish reports from directly observed failures. Confirm the scope of authorized system access.
2. Build the relevant timeline from logs, metrics, traces, deployments, configuration, and dependencies. Record source, collection time, and gaps; account for clock skew and sampling. Avoid copying secrets or sensitive payloads into reports.
3. Form competing falsifiable hypotheses when evidence permits. For each, identify a predicted observation and what would weaken it. A nearby deployment is a candidate cause, not proof.
4. Choose the highest-value safe discriminating check. Prefer scoped reads or isolated reproduction over broad production probes. Update confidence from results; do not repeat ineffective checks indefinitely or invent telemetry that is unavailable.
5. Separate containment from causal correction. Describe the expected effect, downside, and recovery check for each proposed mitigation. Consider ambiguous completion, duplicate effects, and loss of diagnostic evidence before retries, replay, rollback, or restart.

## Result and stopping point

Return observed impact, supporting evidence, leading hypotheses with differentiators, the next check, and mitigation options. State missing telemetry and unresolved questions. Stop at an access or production-action boundary and request the specific authorization or evidence required. Declare recovery only when relevant signals have been observed over an appropriate interval; a quieter dashboard alone may mean lost traffic.

Do not restart services, alter alerts, replay jobs, query sensitive systems, or otherwise act in production without authorization covering that action. An investigation request does not imply it.

## Example

A synthetic dispatch endpoint times out after possibly committing a job. Before adding retries, distinguish failure before commit from a lost response after commit. Check a stable request identifier and deduplication behavior; retrying without an idempotency contract can create duplicate work.
