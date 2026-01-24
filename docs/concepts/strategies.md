# Retry strategies

Strategies can use one of two signatures:

- Context-aware: `strategy(ctx: BackoffContext) -> float`
- Legacy: `strategy(attempt: int, klass: ErrorClass, prev_sleep_s: float | None) -> float`

`BackoffContext` provides:

- `attempt` – 1-based attempt number
- `classification` – structured `Classification` (retry hints, details)
- `remaining_s` – deadline time remaining (seconds)
- `prev_sleep_s` – previous sleep value
- `cause` – `"exception"` for now (future result-based retries add `"result"`)

Built-ins (all return a `StrategyFn`):

- `decorrelated_jitter(base_s=0.25, max_s=30.0)` – sleeps uniformly in `[base_s, prev_sleep*3]`, clamped to `max_s`.
- `equal_jitter(base_s=0.25, max_s=30.0)` – exponential with jitter in `[cap/2, cap]`, `cap = min(max_s, base_s*2^attempt)`.
- `token_backoff(base_s=0.25, max_s=20.0)` – gentler exponential (`1.5^attempt`) with jitter.
- `retry_after_or(fallback, jitter_s=0.25)` – honors `Classification.retry_after_s` when present, otherwise calls `fallback`.

Example:

```python
from redress import RetryPolicy, default_classifier
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter, equal_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=10.0),  # default for most classes
    strategies={
        ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
        ErrorClass.SERVER_ERROR: equal_jitter(max_s=30.0),
    },
)
```

Retry-After-aware example:

```python
from redress import RetryPolicy
from redress.extras import http_retry_after_classifier
from redress.strategies import decorrelated_jitter, retry_after_or

policy = RetryPolicy(
    classifier=http_retry_after_classifier,
    strategy=retry_after_or(decorrelated_jitter(max_s=10.0)),
)
```
