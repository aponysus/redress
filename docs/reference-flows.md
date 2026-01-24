# Reference flows

This page collects runnable end-to-end patterns for common service integrations.

## Policy reuse and per-operation contexts

Create a policy once and reuse it across calls. Use `context()` to bind hooks
and an operation name for a batch of calls.

```python
from redress import Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        deadline_s=30.0,
        max_attempts=5,
    )
)

with policy.context(operation="sync_user") as call:
    call(lambda: do_work())
```

## HTTP downstream call (Retry-After + result-based retries)

This example shows:
- result-based retries (429/5xx) without raising exceptions
- Retry-After honored via `Classification.retry_after_s`
- per-call hooks via `policy.context`

Run:
`uv pip install httpx`
`uv run python docs/snippets/httpx_retry_after.py`

```python
--8<-- "docs/snippets/httpx_retry_after.py"
```

## Worker loop with cooperative abort

This example shows:
- `abort_if` for graceful shutdown
- durable attempt logging via `on_log`
- async policy context reuse

Run:
`uv run python docs/snippets/async_worker_abort.py`

```python
--8<-- "docs/snippets/async_worker_abort.py"
```

## Observability wiring

Event names and stop reasons are exported as `redress.events.EventName` and
`redress.StopReason`. See [Observability](observability.md) for the full contract.

Recommended low-cardinality tags:
- `class`
- `operation`
- `err`
- `stop_reason` (terminal events only)

### Prometheus metric hook

```python
from prometheus_client import Counter
from redress.metrics import prometheus_metric_hook

counter = Counter("redress_events", "Retry events", ["event", "class", "operation", "err"])
hook = prometheus_metric_hook(counter)
policy.call(work, on_metric=hook, operation="sync_user")
```

### OpenTelemetry hooks

```python
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from redress.contrib.otel import otel_hooks

trace.set_tracer_provider(TracerProvider())
metrics.set_meter_provider(MeterProvider())

hooks = otel_hooks(
    tracer=trace.get_tracer("redress"),
    meter=metrics.get_meter("redress"),
)

policy.call(work, **hooks, operation="sync_user")
```

## Migration notes

- `Policy`/`Retry` provide a unified container; `RetryPolicy` remains a compatible shortcut.
- Classifiers may return `Classification` for hints like `retry_after_s`; `ErrorClass` return is still supported.
- Strategies can be context-aware: `(ctx: BackoffContext) -> float`; legacy `(attempt, klass, prev_sleep_s)` is still accepted.
- The `@retry` decorator only injects a default strategy when both `strategy` and `strategies` are omitted.
- `execute()` returns a `RetryOutcome` with `StopReason` and attempt metadata (call still returns/raises).
- `EventName` and `StopReason` are exported for stable observability contracts.
