# Observability contract

## Hook signatures

- Metrics: `on_metric(event: str, attempt: int, sleep_s: float, tags: Dict[str, Any])`
- Logging: `on_log(event: str, fields: Dict[str, Any])` (fields include attempt, sleep_s, tags)

Hook failures are swallowed so they never break the workload; log adapter errors separately if needed.

## Events

- `success` – call succeeded
- `retry` – retry scheduled (includes `sleep_s`)
- `permanent_fail` – non-retriable class (`PERMANENT`, `AUTH`, `PERMISSION`)
- `deadline_exceeded` – wall-clock deadline exceeded
- `max_attempts_exceeded` – global or per-class cap reached
- `max_unknown_attempts_exceeded` – UNKNOWN-specific cap reached

Attempts are 1-based. `sleep_s` is the scheduled delay for retries, otherwise 0.0.

## Tags

- `operation` – optional logical name provided by caller
- `class` – `ErrorClass.name` when available
- `err` – exception class name when available

Avoid payloads or sensitive fields in tags; stick to identifiers.

## Prometheus pattern

```python
from reflexio.metrics import prometheus_metric_hook

policy.call(
    lambda: do_work(),
    on_metric=prometheus_metric_hook(counter),
    operation="sync_user",
)
```

Counter should expose `.labels(event=..., **tags).inc()`.

## OTEL pattern (pseudo-code)

```python
from reflexio.metrics import otel_metric_hook

policy.call(
    lambda: do_work(),
    on_metric=otel_metric_hook(meter, name="reflexio_attempts"),
    operation="sync_user",
)
```

Meter counter should support `.add(1, attributes=attributes)`.

## Alerting ideas

- Rising `retry` or `max_attempts_exceeded` for `RATE_LIMIT`/`SERVER_ERROR` -> backoff/circuit breaker tuning.
- Frequent `permanent_fail` with `AUTH`/`PERMISSION` -> credential/config issues.
- `deadline_exceeded` spikes -> deadline too low or upstream slowness.
