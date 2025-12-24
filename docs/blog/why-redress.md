# Why Naive Retry Logic Fails (and How Redress Tries to Fix It)

Most of the time, retry logic gets added at the last minute:

- “Wrap it in a decorator.”
- “Give it exponential backoff.”
- “Try five times then give up.”

It works in dev. It mostly works in staging. Then production hits, a dependency starts flaking, and those “simple retries” suddenly turn a small blip into a full incident.

The core problem: **naive retries treat all failures the same**. Real systems don’t.

This post walks through how I ended up designing **redress** the way I did: error classification, per-class strategies, and an observability hook instead of a big generic “retry until it works” hammer.

---

# 1. A simple retry isn’t enough

The easiest way to use redress is the `@retry` decorator:

```python
from redress import retry

@retry  # uses default_classifier + decorrelated_jitter(max_s=5.0)
def fetch_user(user_id: str):
    ...
```

With **no arguments**, this does a few things for you:

- Uses `default_classifier` to map exceptions into coarse error classes.
- Uses `decorrelated_jitter(max_s=5.0)` as the backoff strategy.

This already avoids many pitfalls of naive retry loops.

---

# 2. Error classes: not every failure is equal

Redress works around a small set of coarse error classes:

- **PERMANENT**
- **CONCURRENCY**
- **RATE_LIMIT**
- **SERVER_ERROR**
- **TRANSIENT**
- **UNKNOWN**

The default classifier does a best-effort mapping:

- Looks for explicit redress error types.
- Checks numeric codes like `err.status` or `err.code`.
- Uses name heuristics for common DB/API error patterns.
- Falls back to `UNKNOWN` if it can’t place it.

The goal isn’t perfect diagnosis. It’s to separate:

- “retry quickly”
- “retry slowly”
- “don’t retry at all”
- “retry very few times if unknown”

Even this coarse structure avoids a lot of self-inflicted pain.

---

# 3. Using `RetryPolicy` directly

For more control, you work with `RetryPolicy`:

```python
from redress.policy import RetryPolicy
from redress.classify import default_classifier
from redress.strategies import decorrelated_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=10.0),
)

def flaky():
    ...

result = policy.call(flaky)
```

This is the core: it wraps your function, runs it, and applies the retry envelope as needed.

---

# 4. Per-class backoff strategies

You probably want different behavior for:

- `CONCURRENCY` (e.g., DB deadlocks)
- `RATE_LIMIT` (429s)
- `SERVER_ERROR` (5xx)

Here's how to do that:

```python
from redress.policy import RetryPolicy
from redress.classify import default_classifier
from redress.strategies import decorrelated_jitter, equal_jitter
from redress.errors import ErrorClass

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=10.0),  # fallback
    strategies={
        ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=1.0),
        ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
        ErrorClass.SERVER_ERROR: equal_jitter(max_s=30.0),
    },
)
```

All strategies share the same function signature:

```
(attempt, error_class, prev_sleep) -> float
```

Built-ins include `decorrelated_jitter`, `equal_jitter`, and `token_backoff`.

---

# 5. Decorators with real configuration

`@retry` is just a thin wrapper around `RetryPolicy`:

```python
from redress import retry
from redress.classify import default_classifier
from redress.strategies import decorrelated_jitter

@retry(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=3.0),
)
def fetch_user_fast_retry(user_id):
    ...
```

Or reuse a shared policy:

```python
from redress.policy import RetryPolicy

shared_policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=3.0),
)

with shared_policy.context(operation="batch") as do_retry:
    do_retry(fetch_user_fast_retry, "user-1")
    do_retry(fetch_user_fast_retry, "user-2")
```

The context manager version is handy for batching operations under one retry envelope + observability context.

---

# 6. Deadlines, caps, and UNKNOWN protection

A common reliability failure is endlessly retrying unknown errors.

Redress lets you bound them:

```python
policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(),
    deadline_s=60,
    max_attempts=8,
    max_unknown_attempts=2,
)
```

This ensures mystery failures never run wild.

---

# 7. Async retries without a separate mental model

Async support mirrors sync exactly:

```python
from redress import AsyncRetryPolicy
from redress.classify import default_classifier
from redress.strategies import decorrelated_jitter

async_policy = AsyncRetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
)

async def flaky_async():
    ...

await async_policy.call(flaky_async)
```

No separate API, no special strategy types—just async versions of the same policies.

---

# 8. Observability: simple, explicit hooks

Retries hide a lot of behavior unless you surface it intentionally.

Redress exposes one hook:

```python
def metric_hook(event, attempt, sleep_s, tags):
    print(event, attempt, sleep_s, tags)

policy.call(my_op, on_metric=metric_hook)
```

You get structured events:

- `retry`
- `success`
- `permanent_fail`
- `deadline_exceeded`
- `max_attempts_exceeded`
- `max_unknown_attempts_exceeded`

With contextual tags (function name, operation, error class, etc.).  
This is easy to wire into Prometheus, logging, tracing, or anything else.

---

# 9. Why this matters

Redress isn’t trying to out-feature other retry libraries.  
It’s trying to make retry behavior:

- **semantic** (via error classes)
- **predictable** (per-class strategies)
- **bounded** (deadlines & caps)
- **visible** (single metric hook)
- **for both sync and async** (identical mental model)

These small ingredients solve the most common operational problems:
retry storms, hammering rate-limited APIs, and inconsistency across services.

If you want to explore more:

- GitHub: [https://github.com/aponysus/redress](https://github.com/aponysus/redress)
- Docs: [https://aponysus.github.io/redress/](https://aponysus.github.io/redress/)
- PyPI: [https://pypi.org/project/redress/](https://pypi.org/project/redress/)
