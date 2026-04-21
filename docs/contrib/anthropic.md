# Anthropic

`redress.contrib.anthropic` provides Anthropic-specific retry helpers for the Python SDK.

Phase 2 scope:

- `anthropic_classifier`
- `anthropic_aware_backoff(...)`

Use these helpers when you want redress to classify Anthropic SDK exceptions into the existing `ErrorClass` model and honor retry hints exposed through Anthropic response headers.

## Important

Disable the SDK's built-in retries when using redress:

```python
from anthropic import Anthropic

client = Anthropic(max_retries=0)
```

Layering redress on top of SDK-native retries hides real attempt counts and distorts deadlines.

## Minimal example

```python
from anthropic import Anthropic
from redress import Policy, Retry
from redress.contrib.anthropic import anthropic_aware_backoff, anthropic_classifier

client = Anthropic(max_retries=0)

policy = Policy(
    retry=Retry(
        classifier=anthropic_classifier,
        strategy=anthropic_aware_backoff(max_s=30.0),
        deadline_s=120,
        max_attempts=6,
    ),
)

response = policy.call(
    lambda: client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{"role": "user", "content": "hi"}],
    ),
    operation="anthropic.messages.create",
)
```

## Notes

- `anthropic_classifier` maps auth, permission, permanent request errors, conflicts, rate limits, server errors, and transient transport failures into redress's current `ErrorClass` values.
- `anthropic_aware_backoff(...)` is a small ergonomic wrapper around the existing Retry-After-aware strategy pattern with Anthropic-oriented defaults.
- `409` maps to `CONCURRENCY`, not a provider-local fatal bucket.
- `429` responses with `Retry-After` or `anthropic-ratelimit-*-reset` hints populate `Classification.retry_after_s`.
- `overloaded_error` and the dedicated overloaded/service-unavailable SDK exceptions map to `SERVER_ERROR`.

Streaming guidance, full mapping tables, and broader docs integration can expand in later phases.
