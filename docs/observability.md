# Observability contract

## Hook signatures

- Metrics: `on_metric(event: str, attempt: int, sleep_s: float, tags: Dict[str, Any])`
- Logging: `on_log(event: str, fields: Dict[str, Any])` (fields include attempt, sleep_s, tags)

Hook failures are swallowed so they never break the workload; log adapter errors separately if needed.

## Events

Event names are exported as `redress.events.EventName` (values shown below).

- `success` – call succeeded
- `retry` – retry scheduled (includes `sleep_s`)
- `permanent_fail` – non-retriable class (`PERMANENT`, `AUTH`, `PERMISSION`)
- `deadline_exceeded` – wall-clock deadline exceeded
- `max_attempts_exceeded` – global or per-class cap reached
- `max_unknown_attempts_exceeded` – UNKNOWN-specific cap reached
- `no_strategy_configured` – missing strategy for a retryable class
- `scheduled` – retry deferred by a sleep handler
- `aborted` – retry aborted via abort_if or AbortRetryError
- `circuit_opened` – circuit breaker transitions to open
- `circuit_half_open` – circuit breaker transitions to half-open
- `circuit_closed` – circuit breaker transitions to closed
- `circuit_rejected` – breaker rejected a call

Attempts are 1-based. `sleep_s` is the scheduled delay for retries, otherwise 0.0.
Breaker events use `attempt=0` and `sleep_s=0.0`.
Abort events use the number of completed attempts (0 if aborted before the first).
For result-driven failures, `err` is omitted and `cause="result"` is included.

## Stop reasons (terminal only)

Terminal events carry a stable `stop_reason` tag with a small, fixed set:

- `MAX_ATTEMPTS_GLOBAL`
- `MAX_ATTEMPTS_PER_CLASS`
- `DEADLINE_EXCEEDED`
- `MAX_UNKNOWN_ATTEMPTS`
- `NON_RETRYABLE_CLASS`
- `NO_STRATEGY`
- `SCHEDULED`
- `ABORTED`

## Tags

- `operation` – optional logical name provided by caller
- `class` – `ErrorClass.name` when available
- `err` – exception class name when available
- `stop_reason` – terminal reason for stop events only
- `cause` – `"exception"` or `"result"` when a failure triggers retries/stops
- `state` – circuit breaker state (`closed`, `open`, `half_open`) on breaker events

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

## OpenTelemetry hooks

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

policy.call(
    lambda: do_work(),
    **hooks,
    operation="sync_user",
)
```

`otel_hooks` emits spans with attempt events plus metrics:
`redress.retries`, `redress.retry.duration`, `redress.retry.success_after_retries`,
and `redress.circuit.state`. Attributes include `error.class`, `retry.attempt`,
and `operation`. It requires `opentelemetry-api` (and the SDK if you set
providers directly).

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

## OpenTelemetry metric-only hook

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
