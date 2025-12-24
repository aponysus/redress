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
from redress.metrics import prometheus_metric_hook

policy.call(
    lambda: do_work(),
    on_metric=prometheus_metric_hook(counter),
    operation="sync_user",
)
```

Counter should expose `.labels(event=..., **tags).inc()`.

## OTEL pattern (pseudo-code)

```python
from redress.metrics import otel_metric_hook

policy.call(
    lambda: do_work(),
    on_metric=otel_metric_hook(meter, name="redress_attempts"),
    operation="sync_user",
)
```

Meter counter should support `.add(1, attributes=attributes)`.

## Testing hooks

Quick pattern to assert hooks fire without needing real backends:

```python
events = []

def metric(event, attempt, sleep_s, tags):
    events.append((event, attempt, sleep_s, tags))

policy.call(work, on_metric=metric, operation="op")

assert any(e[0] == "retry" for e in events)
```

You can use the same shape for log hooks; ensure tests avoid networked backends and use local spies instead.

## Tag cardinality guidance

- Keep tags low-cardinality (`class`, `operation`, `err`); avoid per-user/request IDs.
- For HTTP, prefer status classes (e.g., map 5xx) via `http_classifier` instead of embedding URLs.
- For DB, map SQLSTATE classes via `sqlstate_classifier` and avoid query text.

## Structured logging example

```python
import structlog
from redress import retry

logger = structlog.get_logger()

def log_hook(event: str, fields: dict[str, object]) -> None:
    logger.info("retry_event", event=event, **fields)

@retry(on_log=log_hook, operation="sync_account")
def do_work():
    ...
```

## OTEL counter example (pseudo-code)

```python
from redress.metrics import otel_metric_hook

meter = ...  # your OTEL meter
metric_hook = otel_metric_hook(meter, name="redress_events")

@retry(on_metric=metric_hook, operation="fetch_user")
def do_work():
    ...
```

## Prometheus exporter sample

```python
from prometheus_client import Counter, start_http_server
from redress.metrics import prometheus_metric_hook
from redress import retry

counter = Counter("redress_events", "Retry events", ["event", "class", "operation", "err"])
metric_hook = prometheus_metric_hook(counter)
start_http_server(8000)

@retry(on_metric=metric_hook, operation="sync_user")
def do_work():
    ...
```

## Alerting ideas

- Rising `retry` or `max_attempts_exceeded` for `RATE_LIMIT`/`SERVER_ERROR` -> backoff/circuit breaker tuning.
- Frequent `permanent_fail` with `AUTH`/`PERMISSION` -> credential/config issues.
- `deadline_exceeded` spikes -> deadline too low or upstream slowness.
