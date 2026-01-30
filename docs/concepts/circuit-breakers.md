# Circuit breakers

Circuit breakers are a first-class part of the unified `Policy` model. They use the
same classification that drives retries, so you get consistent semantics across
retries and fail-fast behavior.

## How it works

- **Closed**: all calls allowed; failures are recorded.
- **Open**: calls are rejected immediately (`CircuitOpenError`).
- **Half-open**: after `recovery_timeout_s`, one probe call is allowed.
  - Success closes the circuit.
  - Failure re-opens it.

A breaker records failures by **ErrorClass**, not by raw exception types. That means
your classifier controls when the breaker trips.

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
