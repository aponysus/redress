# Migrating from Backoff

Keep an inventory of exception filters, result predicates, give-up rules,
wait schedules, and terminal behavior before replacing decorators.

## Map the configuration

| Backoff configuration | Redress configuration |
| --- | --- |
| `on_exception(..., ExceptionType)` | Classifier selecting those exceptions |
| `max_tries=n` | `max_attempts=n`, including the initial call |
| `max_time=t` | `deadline_s=t`; neither should replace client timeouts |
| `giveup=predicate` | Classify matching exceptions as `PERMANENT` |
| `on_predicate(...)` | `result_classifier` returning a retryable class for matching results |
| `expo` and jitter | Choose a Redress strategy and verify the resulting delays |
| `on_backoff`, `on_success`, `on_giveup` | Adapt observability hooks and terminal outcome handling |
| `raise_on_giveup=False` | Explicit application fallback after a failed `execute()` |

Consult the [Backoff documentation](https://github.com/litl/backoff) for the
source options. Redress callbacks and strategy functions have different
signatures; copying them unchanged will not preserve behavior.

## Translate exception filtering

Before:

```python
import backoff

@backoff.on_exception(backoff.expo, TimeoutError, max_tries=5, max_time=30)
def fetch_user():
    return "user"  # Replace with the existing operation.
```

After (standalone and runnable):

```python
from redress import ErrorClass, retry
from redress.strategies import decorrelated_jitter

def classify_timeout(exc):
    if isinstance(exc, TimeoutError):
        return ErrorClass.TRANSIENT
    return ErrorClass.PERMANENT

@retry(
    classifier=classify_timeout,
    strategy=decorrelated_jitter(base_s=0.25, max_s=5.0),
    max_attempts=5,
    deadline_s=30.0,
)
def fetch_user():
    return "user"  # Replace with the same operation.

assert fetch_user() == "user"
```

This preserves exception selection and the total attempt ceiling. It deliberately
changes the wait distribution to decorrelated jitter. If exact timing matters,
implement a strategy using `BackoffContext.attempt` (1-based) and test the delay
sequence. See [Retry strategies](concepts/strategies.md).

Do not replace a narrow exception filter with `default_classifier` without
reviewing the change. Its fallback is `UNKNOWN`; the default
`max_unknown_attempts=2` stops on the third unknown failure. An explicit
classifier avoids unexpected early termination or retries of excluded errors.
For a give-up rule, return `PERMANENT` before selecting a retryable class.

## Translate result predicates and fallback behavior

```python
from redress import ErrorClass, Policy, Retry
from redress.strategies import decorrelated_jitter

policy = Policy(retry=Retry(
    classifier=lambda exc: ErrorClass.PERMANENT,
    result_classifier=lambda value: ErrorClass.TRANSIENT if not value else None,
    strategy=decorrelated_jitter(base_s=0.1, max_s=1.0),
    max_attempts=3,
    deadline_s=5.0,
))

outcome = policy.execute(lambda: [], operation="poll_jobs")
assert not outcome.ok
assert outcome.last_result == []
jobs = outcome.value if outcome.ok else []  # Application-owned fallback.
```

Return `None` from the result classifier for success; return `ErrorClass` or
`Classification` for failure. A boolean predicate alone is not a classifier.
The example retries falsey results and stops immediately on exceptions.

`call()` re-raises ordinary terminal operation exceptions. For result-based
terminal failure it raises `RetryExhaustedError`, rather than returning the last
unsatisfactory result. Use `execute()` and inspect `stop_reason`, `last_result`,
and `last_exception` when preserving a fallback or give-up contract.

## Async, handlers, and Retry-After

Redress `@retry` supports `async def`; await the decorated operation. Explicit
async policies use `AsyncPolicy` with `AsyncRetry`, and their execution methods
must be awaited. Keep client operations asynchronous.

Replace handler dictionaries with the documented hook signatures:
`on_metric(event, attempt, sleep_s, tags)` or `on_log(event, fields)`.
Use `on_attempt_start(ctx)` / `on_attempt_end(ctx)` for attempt context and
`execute()` for terminal application decisions. Metric and log hook exceptions
are swallowed, so test backend adapters independently.

For HTTP Retry-After, use structured classification with `retry_after_s` and
`retry_after_or(...)`; see the [Retry-After starter](starters/retry-after-client.md).
A retry deadline may truncate the selected sleep. It does not interrupt a
running request; configure client timeouts as described in
[Performance tuning](performance-tuning.md).

## Verify before switching traffic

Test success, an allowed exception followed by recovery, give-up exceptions,
exhaustion, falsey results, fallback behavior, and async cancellation where used.
Assert counts and delay sequences with [testing utilities](testing.md).
Avoid nesting the old decorator and the new policy: retries at both layers can
multiply downstream calls. See the [migration overview](migration.md) for the
path to shared budgets and circuit breakers.
