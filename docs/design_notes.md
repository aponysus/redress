# Design notes

## Design invariants

The following constraints are part of the library's design, not incidental
implementation details.

- **Hooks are best-effort:** observability hooks must not break workloads. Hook failures should never change retry outcomes.
- **Behavior must stay bounded:** deadlines, attempt limits, unknown caps, budgets, and breaker thresholds exist to prevent unbounded failure handling.
- **Classification is coarse and semantic:** classifiers should map failures into a small stable set of policy-relevant classes, not mirror every domain taxonomy.
- **Structured outcomes are first-class:** `execute()` and `RetryOutcome` are part of the intended control-flow surface, not a second-tier escape hatch.
- **Sync and async should preserve semantics:** the async API should differ in mechanics, not in the meaning of retries, stop reasons, hooks, and outcomes.
- **Circuit breakers compose with retries:** breaker decisions and retry decisions should use the same classification model and the breaker should observe final operation outcomes, not per-attempt noise.
- **Observability must stay low-cardinality:** tags and event fields should stay useful for production systems and avoid payload-style data.

- **Unified policy model:** `Policy` / `AsyncPolicy` are the primary containers. Retry is one optional component (`Retry` / `AsyncRetry`) rather than the only execution model.
- **Backward-compatible sugar:** `RetryPolicy` and `AsyncRetryPolicy` remain convenience wrappers for retry-only use cases, but they intentionally mirror the unified policy semantics.
- **Circuit breakers wrap operations, not attempts:** Breakers observe the final operation outcome after retry processing so fail-fast behavior and retry behavior stay coordinated.
- **Strict envelopes:** Deadline and max-attempts are enforced before each attempt; sleeps are capped to remaining deadline to avoid overruns.
- **Classification first:** Policies are domain-agnostic; callers map exceptions to `ErrorClass` via classifiers (default or custom).
- **Per-class backoff:** Strategies are looked up by class, falling back to a default; absence of a strategy is a hard error.
- **Result and exception symmetry:** Retry decisions can be driven by exceptions or returned results; both feed the same stop reasons and outcome surface.
- **Deferred execution is first-class:** Sleep handlers can choose `SleepDecision.DEFER`, allowing queue/worker systems to reschedule externally instead of sleeping inline.
- **Best-effort hooks:** Metric/log hooks are isolated—exceptions are swallowed so retries never break due to observability failures.
- **Deterministic jitter bounds:** Built-in strategies clamp to configured maxima; property-based tests assert bounds.
- **Sync/async symmetry:** `Policy` / `AsyncPolicy`, `Retry` / `AsyncRetry`, and the `@retry` decorator share the same mental model.
- **Context reuse:** Context managers bind hooks/operations once for batches; avoid repeating kwargs on every call.
- **Structured terminal outcomes:** `execute()` returns `RetryOutcome` with stop reason, attempts, and last failure information so integrations do not need to infer lifecycle state from hook events alone.
- **Unknowns:** `max_unknown_attempts` prevents unbounded retries on unclassified errors; deadline remains a global guardrail.
