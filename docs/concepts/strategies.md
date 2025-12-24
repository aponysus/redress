# Retry strategies

Built-ins (all return a `StrategyFn`):

- `decorrelated_jitter(base_s=0.25, max_s=30.0)` – sleeps uniformly in `[base_s, prev_sleep*3]`, clamped to `max_s`.
- `equal_jitter(base_s=0.25, max_s=30.0)` – exponential with jitter in `[cap/2, cap]`, `cap = min(max_s, base_s*2^attempt)`.
- `token_backoff(base_s=0.25, max_s=20.0)` – gentler exponential (`1.5^attempt`) with jitter.

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
