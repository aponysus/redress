# HTTP client with sane defaults

Use this starter when you need a basic HTTP client policy with explicit bounds,
predictable retry behavior, and low-cardinality observability.

```python
import httpx

from redress import Policy, Retry, default_classifier
from redress.contrib.httpx import RetryingHttpxClient, default_result_classifier
from redress.strategies import decorrelated_jitter, retry_after_or

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        result_classifier=default_result_classifier,
        strategy=retry_after_or(decorrelated_jitter(max_s=5.0)),
        max_attempts=4,
        deadline_s=10.0,
        max_unknown_attempts=2,
    ),
)

with httpx.Client(timeout=3.0, base_url="https://api.example.com") as client:
    upstream = RetryingHttpxClient(client, policy)
    response = upstream.get("/users/123")
```

Why these defaults:

- `deadline_s=10.0` keeps the failure envelope bounded
- `max_attempts=4` is enough for transient recovery without long tails
- `default_result_classifier` handles common HTTP response retry cases
- `retry_after_or(...)` respects `Retry-After` when present
- `max_unknown_attempts=2` keeps broad unknown failures conservative

For the core API surface, see [Usage](../usage.md). For more HTTP-specific
patterns, see [HTTP recipes](../recipes/http.md).
