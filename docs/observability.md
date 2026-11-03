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
- `budget_exhausted` – retry budget depleted
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
- `BUDGET_EXHAUSTED`
- `SCHEDULED`
- `ABORTED`
- 
`ABORTED` is emitted when `abort_if` requests an abort or a sleep handler
returns `SleepDecision.ABORT`.

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

The helper uses the labels declared on the Prometheus counter, ignoring extra
tags. Existing counters labeled only by `event`, or by `event` and `operation`,
continue to work without configuration changes. Missing or `None` values become
empty strings: a counter that also declares `class` records success with
`class=""`. Other values are converted to strings. You can also pass `label_names`
explicitly, matching the labels declared on the counter.

## Prometheus contrib hook

```python
from prometheus_client import Counter, Histogram
from redress.contrib.prometheus import prometheus_hooks

event_counter = Counter(
    "redress_events_total",
    "redress retry lifecycle events",
    ["event", "class", "operation"],
)
retry_sleep = Histogram(
    "redress_retry_sleep_seconds",
    "scheduled retry delays",
    ["class", "operation"],
)

hooks = prometheus_hooks(
    events=event_counter,
    retry_sleep_seconds=retry_sleep,
)

policy.call(lambda: do_work(), **hooks, operation="sync_user")
```

`prometheus_hooks` increments an event counter for every lifecycle event and,
when a histogram is provided, observes retry sleep durations for `retry` events.
With label configuration omitted, each metric's declared schema determines its
labels. The example above uses:

| Metric | Example labels | Optional configuration argument |
| --- | --- | --- |
| Event counter | `event`, `class`, `operation` | `event_labels` |
| Retry-delay histogram | `class`, `operation` | `retry_sleep_labels` |

Each metric receives only its declared or explicitly configured labels. Missing
or `None` values become empty strings, and other values are converted to strings.
The `event` label, if selected, always comes from the event argument. Tags such as
`cause`, `err`, `stop_reason`, and `state` are ignored unless included in that
metric's schema. The label schema stays fixed across retry, success, exhaustion,
abort, and breaker events.

For wrappers that do not expose Prometheus label metadata, both helpers preserve
the previous behavior of forwarding all event tags. To select a fixed schema for
such a wrapper, pass `label_names` to `prometheus_metric_hook`, or `event_labels`
and `retry_sleep_labels` to `prometheus_hooks`. These names must match the wrapped
metric's declared labels. Use `()` to explicitly select an unlabeled metric.
Explicit configuration takes precedence over inferred names. Both helpers copy
the names when created and reject duplicate names or a bare string.

Ordinary metric failures are ignored without affecting workload outcomes. The
counter and histogram are isolated independently: a counter failure still allows
the retry-delay observation. Cancellation and process-exit exceptions propagate.

The [runnable example](snippets/prometheus_contrib.py) uses an isolated registry
and prints samples for one retry followed by success. Run it from the checkout
with `uv run --extra prometheus python docs/snippets/prometheus_contrib.py`.

## Datadog contrib hook

```python
from datadog import statsd
from redress.contrib.datadog import datadog_hooks

hooks = datadog_hooks(
    statsd=statsd,
    prefix="svc.redress",
    constant_tags=["env:prod"],
)

policy.call(lambda: do_work(), **hooks, operation="sync_user")
```

`datadog_hooks` emits:
- `{prefix}.events` with tags like `event:retry`, `class:RATE_LIMIT`, `operation:sync_user`
- `{prefix}.retry.sleep_seconds` histograms for retry delays

## Sentry contrib hook

```python
import sentry_sdk
from redress.contrib.sentry import sentry_hooks

sentry_sdk.init(dsn="...")
hooks = sentry_hooks(sentry=sentry_sdk)

policy.call(lambda: do_work(), **hooks, operation="sync_user")
```

`sentry_hooks` turns hook log events into breadcrumbs and captures terminal
failure events as Sentry messages by default.

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
metric_hook = prometheus_metric_hook(counter, label_names=("event", "class", "operation", "err"))
start_http_server(8000)

@retry(on_metric=metric_hook, operation="sync_user")
def do_work():
    ...
```

## Alerting ideas

- Rising `retry` or `max_attempts_exceeded` for `RATE_LIMIT`/`SERVER_ERROR` -> backoff/circuit breaker tuning.
- Frequent `permanent_fail` with `AUTH`/`PERMISSION` -> credential/config issues.
- `deadline_exceeded` spikes -> deadline too low or upstream slowness.
