# Circuit breakers

Read this page when you want the breaker mental model: states, thresholds, and
how breaker decisions compose with retries inside the unified policy container.

For the canonical configuration pattern, see [Usage](../usage.md). For
downstream-specific application patterns, start in `Recipes`.

Circuit breakers are a first-class part of the unified `Policy` model. They use the
same classification that drives retries, so you get consistent semantics across
retries and fail-fast behavior.

## How it works

- **Closed**: all calls allowed; failures are recorded.
- **Open**: calls are rejected immediately (`CircuitOpenError`).
- **Half-open**: after `recovery_timeout_s`, one probe call is allowed.
  - Success closes the circuit.
  - Failure re-opens it.
  - Cancelling or interrupting an unfinished probe releases its admission. The
    circuit stays half-open and the next call can probe immediately.

A breaker records failures by **ErrorClass**, not by raw exception types. That means
your classifier controls when the breaker trips.

## Cancellation and overlapping executions

`Policy` and `AsyncPolicy` track admission for each `call()` or `execute()`, with
or without retries. If execution exits before recording a final breaker outcome,
its admission is released. This includes cancellation during the operation or
retry sleep, cancellation raised by callbacks, and exceptions escaping retry
processing. Cancellation, `KeyboardInterrupt`, and `SystemExit` still propagate;
cleanup does not turn them into successful results or structured outcomes.

Only the current recovery probe may close or re-open the half-open circuit.
Results and cleanup from executions admitted before an intervening circuit
transition are ignored by the breaker. A rejected call or a preflight abort has
no admission to release. Once a final outcome has been recorded, an exception
from a later callback cannot release a newer probe.

Use the policies for concurrent execution with these ownership guarantees. The
low-level `allow()`, `record_success()`, `record_failure(klass)`, and
`record_cancel()` methods retain their manual state-management behavior; callers
using them directly must coordinate their own admissions and completions.

## Configuration knobs

- `failure_threshold`: number of failures in the window to open the circuit.
- `window_s`: rolling time window for failure counting.
- `recovery_timeout_s`: how long to wait before a half-open probe.
- `trip_on`: which ErrorClass values should count toward opening.
- `class_thresholds`: per-class thresholds (override global threshold for a class).

## Copy/paste example

```python
from redress import CircuitBreaker, ErrorClass, Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

breaker = CircuitBreaker(
    failure_threshold=3,
    window_s=30.0,
    recovery_timeout_s=10.0,
    trip_on={ErrorClass.SERVER_ERROR, ErrorClass.TRANSIENT},
)

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        max_attempts=3,
        deadline_s=6.0,
    ),
    circuit_breaker=breaker,
)

result = policy.call(do_work, operation="downstream_call")
```

## Observability

Breaker events are emitted via `on_metric` / `on_log` hooks with:

- `event`: `circuit_opened`, `circuit_half_open`, `circuit_closed`, `circuit_rejected`
- `state`: `open`, `half_open`, `closed`
- `class`: ErrorClass (when applicable)

These tags are low-cardinality by design. Avoid attaching request IDs, URLs, or
raw error messages to hooks.
