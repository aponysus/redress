# redress usage patterns

## Unified Policy model

`Policy` is the unified resilience container. Configure retries via `Retry`,
or use `RetryPolicy` as a convenient shortcut.

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
```

## Circuit breakers

Use `CircuitBreaker` with the unified policy to fail fast when a downstream is unhealthy.

```python
from redress import CircuitBreaker, ErrorClass, Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

breaker = CircuitBreaker(
    failure_threshold=5,
    window_s=60.0,
    recovery_timeout_s=30.0,
    trip_on={ErrorClass.TRANSIENT, ErrorClass.SERVER_ERROR},
)

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
    ),
    circuit_breaker=breaker,
)
```

## Per-class strategies and limits

```python
from redress.policy import RetryPolicy
from redress.errors import ErrorClass
from redress.classify import default_classifier
from redress.strategies import decorrelated_jitter, equal_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=10.0),  # default for most classes
    strategies={
        ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=1.0),
        ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
        ErrorClass.SERVER_ERROR: equal_jitter(max_s=30.0),
    },
    per_class_max_attempts={
        ErrorClass.RATE_LIMIT: 3,
        ErrorClass.SERVER_ERROR: 5,
    },
)
```

Per-class limit semantics:
- `0` = no retries for that class (stop on first failure)
- `1` = one retry (two total attempts for that class)
- `2` = two retries (three total attempts for that class)

## Pluggable sleep handler (defer instead of sleeping)

Use a sleep handler to persist retry timing and exit the loop without blocking.

```python
from redress import RetryPolicy, SleepDecision, StopReason, default_classifier
from redress.strategies import decorrelated_jitter

def schedule(ctx, sleep_s: float) -> SleepDecision:
    save_next_attempt(ctx.attempt, sleep_s, ctx.classification.klass)
    return SleepDecision.DEFER

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
)

outcome = policy.execute(do_work, sleep=schedule)
if outcome.stop_reason is StopReason.SCHEDULED:
    ...
```

## Classification context & context-aware strategies

Classifiers may return `Classification` to pass hints like Retry-After. The retry
loop normalizes all classifier outputs to `Classification`, and context-aware
strategies receive a `BackoffContext`.

```python
from redress import RetryPolicy
from redress.extras import http_retry_after_classifier
from redress.strategies import decorrelated_jitter, retry_after_or

policy = RetryPolicy(
    classifier=http_retry_after_classifier,
    strategy=retry_after_or(decorrelated_jitter(max_s=10.0)),
)
```

Legacy strategies with `(attempt, klass, prev_sleep_s)` are still supported.
Strategies must accept exactly one required positional argument (ctx) or three
required positional arguments (attempt, klass, prev_sleep_s).

## Result-based retries

Use `result_classifier` to retry on return values instead of exceptions.

```python
from redress import RetryPolicy
from redress.classify import Classification, default_classifier
from redress.errors import ErrorClass, RetryExhaustedError
from redress.strategies import decorrelated_jitter, retry_after_or

def result_classifier(resp) -> ErrorClass | Classification | None:
    status = getattr(resp, "status", None) or getattr(resp, "status_code", None)
    if status == 429:
        retry_after = None
        header = getattr(resp, "headers", {}).get("Retry-After")
        if isinstance(header, str) and header.isdigit():
            retry_after = float(header)
        return Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=retry_after)
    if status is not None and status >= 500:
        return ErrorClass.SERVER_ERROR
    return None

policy = RetryPolicy(
    classifier=default_classifier,
    result_classifier=result_classifier,
    strategy=retry_after_or(decorrelated_jitter(max_s=10.0)),
)

try:
    policy.call(fetch_response)
except RetryExhaustedError as err:
    ...
```

## Using `operation` to distinguish call sites

```python
def fetch_profile():
    ...

policy.call(fetch_profile, operation="fetch_profile")
```

Metrics/logs include `operation=fetch_profile`, letting you split dashboards per call site.

## RetryConfig for shared settings

```python
from redress.config import RetryConfig
from redress.policy import RetryPolicy
from redress.classify import default_classifier

cfg = RetryConfig(
    deadline_s=45.0,
    max_attempts=6,
    per_class_max_attempts={
        ErrorClass.RATE_LIMIT: 2,
        ErrorClass.SERVER_ERROR: 4,
    },
)

policy = RetryPolicy.from_config(cfg, classifier=default_classifier)
```

## Async usage

`AsyncRetryPolicy` mirrors the sync API but awaits your callable and uses `asyncio.sleep` for backoff.

```python
import asyncio
from redress import AsyncRetryPolicy, default_classifier
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter

async_policy = AsyncRetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=2.0),
    strategies={ErrorClass.RATE_LIMIT: decorrelated_jitter(min_s=1.0, max_s=8.0)},
    deadline_s=10.0,
    max_attempts=5,
)

async def fetch_user() -> str:
    ...

asyncio.run(async_policy.call(fetch_user, operation="fetch_user"))
```

Observability hooks (`on_metric`, `on_log`), deadlines, and per-class limits behave the same as the sync policy.

## Logging and metrics hooks together

```python
from redress.metrics import prometheus_metric_hook

def log_hook(event: str, fields: dict) -> None:
    logger.info("retry_event", extra={"event": event, **fields})

policy.call(
    lambda: do_work(),
    on_metric=prometheus_metric_hook(counter),
    on_log=log_hook,
    operation="sync_account",
)
```

## Attempt lifecycle hooks

```python
from redress import AttemptDecision

def on_attempt_end(ctx) -> None:
    if ctx.decision is AttemptDecision.RETRY:
        record_retry(ctx.attempt, ctx.classification.klass, ctx.sleep_s)

policy.call(
    lambda: do_work(),
    on_attempt_end=on_attempt_end,
    operation="sync_account",
)
```

## Decorator-based retries (sync + async)

The `retry` decorator wraps functions and chooses the right policy automatically based on whether the function is sync or async.

```python
from redress import retry, default_classifier
from redress.strategies import decorrelated_jitter

@retry  # defaults to default_classifier + decorrelated_jitter(max_s=5.0)
def fetch_user():
    ...

@retry
async def fetch_user_async():
    ...
```

If you omit both `strategy` and `strategies`, the decorator injects
`decorrelated_jitter(max_s=5.0)` as a default. If you provide a per-class
`strategies` mapping without a default, the decorator will not add one.

Hooks and `operation` can be set on the decorator. The `operation` defaults to the function name when omitted.

## Context managers for repeated calls

You can bind hooks/operation once and reuse:

```python
policy = RetryPolicy(..., classifier=default_classifier, strategy=decorrelated_jitter())

with policy.context(operation="batch") as retry:
    retry(do_thing)
    retry(do_other, arg1, arg2)
```

Async variant:

```python
async with async_policy.context(operation="batch") as retry:
    await retry(do_async_work)
```

## Structured outcomes

Use `execute()` when you want metadata without parsing hooks:

```python
outcome = policy.execute(do_work, operation="sync_task")

if outcome.ok:
    print(outcome.value, outcome.attempts)
else:
    print(outcome.stop_reason, outcome.last_class)
```

Capture an opt-in per-attempt timeline for debugging:

```python
outcome = policy.execute(do_work, capture_timeline=True)

if outcome.timeline is not None:
    for event in outcome.timeline.events:
        print(event.attempt, event.event, event.stop_reason)
```

You can also pass an explicit collector:

```python
from redress import RetryTimeline

timeline = RetryTimeline()
outcome = policy.execute(do_work, capture_timeline=timeline)
```

## Cooperative abort (shutdown/drain)

Worker loops often need to stop retries when shutting down. Use `abort_if` or
raise `AbortRetryError` inside your callable:

```python
import threading
from redress import AbortRetryError, RetryPolicy, default_classifier
from redress.strategies import decorrelated_jitter

shutdown = threading.Event()

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
)

def abort_if() -> bool:
    return shutdown.is_set()

try:
    policy.call(do_work, abort_if=abort_if)
except AbortRetryError:
    pass
```

## Helper classifiers

`redress.extras` provides domain-oriented classifiers:

- `http_classifier` – maps HTTP status codes (e.g., 429→RATE_LIMIT, 500→SERVER_ERROR, 408→TRANSIENT).
- `sqlstate_classifier` – maps SQLSTATE codes (e.g., 40001/40P01→CONCURRENCY, HYT00/08xxx→TRANSIENT, 28xxx→AUTH).
- `urllib3_classifier` – maps urllib3 transport errors and HTTP status codes.
- `redis_classifier` – maps redis-py connection/auth errors.
- `aiohttp_classifier` – maps aiohttp client errors and HTTP status codes.
- `grpc_classifier` – maps gRPC status codes to ErrorClass.
- `boto3_classifier` – maps botocore ClientError codes and AWS transport errors.

Optional classifiers are shipped as extras:

- `redress[urllib3]`
- `redress[redis]`
- `redress[aiohttp]`
- `redress[grpc]`
- `redress[boto3]`

### Optional classifier example

Available classifiers (extras): `urllib3_classifier`, `redis_classifier`, `aiohttp_classifier`,
`grpc_classifier`, `boto3_classifier`, `pyodbc_classifier`. All are used the same way—pass them as
the policy classifier.

```python
from redress import RetryPolicy
from redress.extras import urllib3_classifier
from redress.strategies import decorrelated_jitter

policy = RetryPolicy(
    classifier=urllib3_classifier,
    strategy=decorrelated_jitter(max_s=3.0),
)
```

Swap in any of the other optional classifiers above as needed.

`default_classifier` includes name-based heuristics for convenience. If you want more predictable
behavior, use `strict_classifier` (same logic without name heuristics) or supply your own
domain-specific classifier.

## PyODBC classification example

`redress` stays dependency-free, so database-specific classifiers live in extras. Use `pyodbc_classifier` for a SQLSTATE-based mapper.

```python
from redress import retry
from redress.strategies import decorrelated_jitter
from redress.extras import pyodbc_classifier

@retry(
    classifier=pyodbc_classifier,
    strategy=decorrelated_jitter(max_s=3.0),
    strategies={},  # optional per-class overrides
)
def run_query():
    ...
```
