# Testing utilities

`redress.testing` provides helpers for deterministic retries, spyable policies,
and controllable circuit breakers in unit tests.

## Deterministic backoff

Use deterministic strategies to avoid flaky sleeps.

```python
from redress import RetryPolicy, default_classifier
from redress.testing import DeterministicStrategy

strategy = DeterministicStrategy([0.0, 0.0, 0.1], default=0.1)

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=strategy,
    max_attempts=3,
)
```

`DeterministicStrategy.calls` stores every `BackoffContext` passed in.

## Instant retries / no retries

```python
from redress.testing import instant_retries, no_retries
from redress import RetryPolicy, default_classifier

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=instant_retries,
    max_attempts=3,
)

cfg = no_retries(deadline_s=5.0)
```

`no_retries()` returns a `RetryConfig` with `max_attempts=1`.

## RecordingPolicy

Wrap any policy and record arguments/outcomes without changing behavior.

```python
from redress import RetryPolicy, default_classifier
from redress.testing import RecordingPolicy, instant_retries

policy = RecordingPolicy(
    RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        max_attempts=2,
    )
)

policy.call(lambda: "ok", operation="demo")
assert policy.calls[-1].kwargs["operation"] == "demo"
```

`RecordingPolicy` also supports async policies; it records after awaiting.

Use it to assert wrapper/decorator forwarding without a full metric/log spy
setup (e.g., verify `operation`, `on_metric`, or `on_log` are passed through).

## FakePolicy

Use a lightweight stub when you only need outcomes.

```python
from redress.testing import FakePolicy

policy = FakePolicy(call_result="ok")
assert policy.call(lambda: "ignored") == "ok"
```

## FakeCircuitBreaker

Control circuit behavior in unit tests.

```python
from redress import Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter
from redress.testing import BreakerDecision, FakeCircuitBreaker
from redress.circuit import CircuitState

breaker = FakeCircuitBreaker(
    allow_sequence=[
        BreakerDecision(False, CircuitState.OPEN, "circuit_rejected"),
        BreakerDecision(True, CircuitState.HALF_OPEN, "circuit_half_open"),
    ]
)

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=0.0),
        max_attempts=1,
    ),
    circuit_breaker=breaker,
)
```
