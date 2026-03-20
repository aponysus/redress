# Testing Redress-using code

Use this page when you want deterministic tests around retry behavior, stop
reasons, and observability without depending on real sleeps or flaky backends.

## What `redress.testing` is for

The `redress.testing` helpers exist to make resilience behavior testable without
turning every test into a timing problem.

Use them to:

- make retries deterministic
- avoid real sleeping
- assert `RetryOutcome.stop_reason`
- record policy calls and executions
- stub circuit-breaker behavior cleanly

## Deterministic retry timing

Use `DeterministicStrategy` when you want fixed backoff values instead of
 random jitter.

```python
from redress import RetryPolicy, default_classifier
from redress.testing import DeterministicStrategy

strategy = DeterministicStrategy([0.0, 0.0, 0.0])

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=strategy,
    max_attempts=4,
    deadline_s=5.0,
)
```

This makes tests predictable and lets you assert how many retry decisions were
made without caring about timing variance.

## Zero-sleep tests

If you only want retries to happen immediately, use `instant_retries`.

```python
from redress import RetryPolicy, default_classifier
from redress.testing import instant_retries

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=instant_retries,
    max_attempts=3,
)
```

This is often the fastest default for retry-unit tests.

## Retry-disabled tests

Use `no_retries()` when the test is about one-shot execution semantics and you
want retry behavior disabled explicitly.

```python
from redress import RetryPolicy, default_classifier
from redress.testing import no_retries

cfg = no_retries(deadline_s=10.0)
policy = RetryPolicy.from_config(cfg, classifier=default_classifier)
```

This is useful when you want to assert classification, hook payloads, or
 no-retry terminal behavior without accidental retries.

## Asserting structured stop reasons

Use `execute()` when the caller cares why retries stopped.

```python
from redress import RetryPolicy, default_classifier
from redress.testing import instant_retries

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=instant_retries,
    max_attempts=2,
)

outcome = policy.execute(do_work, operation="sync_task")
assert outcome.stop_reason is not None
```

`RetryOutcome` is usually easier to assert against than catching terminal
exceptions and inferring what happened.

## Recording policy calls

Use `RecordingPolicy` when the test is about how your code uses a policy, not
about the retry engine itself.

```python
from redress.testing import RecordingPolicy

wrapped = RecordingPolicy(policy)

wrapped.call(do_work, operation="sync_task")
assert wrapped.calls[0].kwargs["operation"] == "sync_task"
```

This is a good fit for framework glue, wrappers, and contrib-style helpers.

## Fake policies

Use `FakePolicy` when you want a controllable stub with preset call or execute
behavior.

```python
from redress.testing import FakePolicy

policy = FakePolicy(call_result="ok")
assert policy.call(lambda: "ignored") == "ok"
```

This is often simpler than building mock-heavy tests.

## Fake circuit breakers

Use `FakeCircuitBreaker` and `BreakerDecision` when your test is about breaker
allow/reject behavior.

```python
from redress.circuit import CircuitState
from redress.testing import BreakerDecision, FakeCircuitBreaker

breaker = FakeCircuitBreaker(
    allow_sequence=[
        BreakerDecision(allowed=False, state=CircuitState.OPEN, event="circuit_rejected"),
    ]
)
```

This lets you test policy composition and integration behavior without relying
on rolling windows or real time.

## Testing hook emission

Prefer local spies over real backends.

```python
events = []

def metric(event, attempt, sleep_s, tags):
    events.append((event, attempt, sleep_s, tags))

policy.call(do_work, on_metric=metric, operation="sync_task")
assert any(name == "retry" for name, *_rest in events)
```

Keep hook tests focused on payload shape and event sequencing, not backend SDKs.

## Practical testing rules

- Use `instant_retries` or `DeterministicStrategy` by default in tests.
- Use `execute()` when asserting stop reasons.
- Use `RecordingPolicy` or `FakePolicy` for integration/unit tests around your own wrappers.
- Avoid real sleeping and real networked observability backends in tests.
- Treat timelines and hook payloads as structured data, not log text.
