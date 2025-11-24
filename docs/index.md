# reflexio

Composable retry policies with pluggable classifiers, per-class backoff, and structured hooks.

## Quick start

```python
from reflexio import retry

@retry  # uses default_classifier + decorrelated_jitter(max_s=5.0)
def fetch_user():
    ...
```

Async uses the same decorator, or `AsyncRetryPolicy` directly.

## Where to go next

- [Getting started](getting-started.md) – install and first examples.
- [Concepts](concepts/error-classes.md) – error classes, strategies, policies, decorators.
- [Observability](observability.md) – metrics/log hooks and patterns.
- [Examples](examples/index.md) – runnable snippets for HTTP, DB, workers, FastAPI, benchmarks.
