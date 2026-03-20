# 429-aware client with Retry-After

Use this starter when the upstream uses `429 Too Many Requests` and you want the
client to respect `Retry-After` rather than treating rate limiting as a generic
transient error.

```python
from redress import RetryPolicy
from redress.extras import http_retry_after_classifier
from redress.strategies import decorrelated_jitter, retry_after_or

policy = RetryPolicy(
    classifier=http_retry_after_classifier,
    strategy=retry_after_or(decorrelated_jitter(max_s=30.0)),
    max_attempts=5,
    deadline_s=20.0,
    max_unknown_attempts=2,
)

response = policy.call(fetch_rate_limited_resource, operation="api.fetch")
```

Why these defaults:

- `http_retry_after_classifier` extracts rate-limit semantics explicitly
- `retry_after_or(...)` honors server-provided delay hints first
- the fallback jitter strategy still handles generic transient failures
- bounded attempts and deadline keep throttling from stretching endlessly

For the core retry surface, see [Usage](../usage.md). For more HTTP retry
patterns, see [HTTP recipes](../recipes/http.md).
