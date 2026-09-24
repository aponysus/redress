# Migrating from Tenacity

Start by recording which exceptions and results your application retries, its
attempt limits, its wait schedule, and what callers receive on exhaustion.
Migrate one operation at a time and preserve those behaviors in tests.

## Map the configuration

| Tenacity configuration | Redress configuration |
| --- | --- |
| `retry_if_exception_type(...)` | A classifier returning a retryable `ErrorClass` for those exceptions |
| `stop_after_attempt(n)` | `max_attempts=n`, including the initial call |
| `stop_after_delay(t)` | `deadline_s=t`; check the timing differences below |
| `wait_fixed(t)` | A strategy returning `t` |
| `wait_exponential(...)` | A custom strategy for the same schedule, or an intentional switch to jitter |
| `retry_if_result(predicate)` | `result_classifier` returning a class when the result needs retrying |
| `reraise=True` | `call()` re-raises ordinary terminal operation exceptions |
| `retry_error_callback` | Handle a failed `execute()` outcome explicitly |

See the [Tenacity documentation](https://tenacity.readthedocs.io/en/latest/)
for the source options. These are migration starting points, not a drop-in API.

## Preserve exception selection first

Before:

```python
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

@retry(
    retry=retry_if_exception_type(TimeoutError),
    stop=stop_after_attempt(5),
    wait=wait_fixed(0.1),
    reraise=True,
)
def fetch_user():
    return "user"  # Replace with the existing operation.
```

After (standalone and runnable):

```python
from redress import ErrorClass, retry

def classify_timeout(exc):
    if isinstance(exc, TimeoutError):
        return ErrorClass.TRANSIENT
    return ErrorClass.PERMANENT

def fixed_wait(ctx):
    return 0.1

@retry(
    classifier=classify_timeout,
    strategy=fixed_wait,
    max_attempts=5,
    deadline_s=30.0,
)
def fetch_user():
    return "user"  # Replace with the same operation.

assert fetch_user() == "user"
```

The explicit classifier preserves the exception allowlist. Substituting
`default_classifier` would change it: that classifier uses error types, codes,
and name heuristics, then falls back to `UNKNOWN`. With the default
`max_unknown_attempts=2`, the third unknown failure stops retrying, possibly
before the global attempt limit. Prefer a deliberate classifier to disabling
that protection.

The example also introduces a 30-second retry deadline. A deadline limits retry
decisions and sleep, but does not interrupt an in-flight operation. Configure
client timeouts too; see [Performance tuning](performance-tuning.md).

## Move result handling and terminal decisions into a policy

```python
from redress import ErrorClass, Policy, Retry
from redress.strategies import decorrelated_jitter

policy = Policy(retry=Retry(
    classifier=lambda exc: ErrorClass.PERMANENT,
    result_classifier=lambda value: ErrorClass.TRANSIENT if value is None else None,
    strategy=decorrelated_jitter(base_s=0.1, max_s=1.0),
    max_attempts=3,
    deadline_s=5.0,
))

outcome = policy.execute(lambda: "user", operation="fetch_user")
assert outcome.ok and outcome.value == "user"
```

A result classifier returns `None` for success, not a boolean predicate.
On a failed outcome inspect `stop_reason`, `last_result`, and `last_exception`
before choosing an application fallback. `call()` raises `RetryExhaustedError`
for terminal result failures; ordinary exception failures propagate the
operation exception. Do not carry a Tenacity `RetryError` catch over unchanged.
The jitter above is an intentional timing change, not exponential-wait parity.

## Async operations and callbacks

The Redress `@retry` decorator recognizes `async def` functions; await the
wrapped function normally. For explicit policies use
`AsyncPolicy(retry=AsyncRetry(...))` and await `call()` or `execute()`.
Use an async client inside that operation to avoid blocking the event loop.

Rewrite callback adapters around Redress payloads:
`on_attempt_start(ctx)` and `on_attempt_end(ctx)` receive `AttemptContext`;
`before_sleep(ctx, sleep_s)` receives `BackoffContext` and the delay.
`on_metric(event, attempt, sleep_s, tags)` and `on_log(event, fields)` are
best-effort observability hooks. Callback objects and firing conditions are
not interchangeable with Tenacity retry state. See [Observability](observability.md).

## Verify the migration

Test immediate success, selected exceptions followed by success, an excluded
exception, exhaustion, and result-based failure if used. Assert call counts,
terminal exceptions or outcomes, and recorded delays. Add cancellation coverage
for async operations. Use [testing utilities](testing.md) to avoid real sleeps.
Only introduce shared budgets or breakers after the basic migration passes.
See the [migration overview](migration.md) for policy composition.
