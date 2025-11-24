# Design notes

- **Strict envelopes:** Deadline and max-attempts are enforced before each attempt; sleeps are capped to remaining deadline to avoid overruns.
- **Classification first:** Policies are domain-agnostic; callers map exceptions to `ErrorClass` via classifiers (default or custom).
- **Per-class backoff:** Strategies are looked up by class, falling back to a default; absence of a strategy is a hard error.
- **Best-effort hooks:** Metric/log hooks are isolated—exceptions are swallowed so retries never break due to observability failures.
- **Deterministic jitter bounds:** Built-in strategies clamp to configured maxima; property-based tests assert bounds.
- **Sync/async symmetry:** `RetryPolicy` and `AsyncRetryPolicy` mirror semantics; `@retry` decorator auto-picks the right one.
- **Context reuse:** Context managers bind hooks/operations once for batches; avoid repeating kwargs on every call.
- **Unknowns:** `max_unknown_attempts` prevents unbounded retries on unclassified errors; deadline remains a global guardrail.
