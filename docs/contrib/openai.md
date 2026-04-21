# OpenAI

`redress.contrib.openai` provides OpenAI-specific retry helpers for the Python SDK.

Phase 1 scope:

- `openai_classifier`
- `openai_aware_backoff(...)`

Use these helpers when you want redress to classify OpenAI SDK exceptions into the existing `ErrorClass` model and honor retry hints exposed through OpenAI response headers.

## Important

Disable the SDK's built-in retries when using redress:

```python
from openai import OpenAI

client = OpenAI(max_retries=0)
```

Layering redress on top of SDK-native retries hides real attempt counts and distorts deadlines.

## Minimal example

```python
from openai import OpenAI
from redress import Policy, Retry
from redress.contrib.openai import openai_aware_backoff, openai_classifier

client = OpenAI(max_retries=0)

policy = Policy(
    retry=Retry(
        classifier=openai_classifier,
        strategy=openai_aware_backoff(max_s=30.0),
        deadline_s=120,
        max_attempts=6,
    ),
)

response = policy.call(
    lambda: client.responses.create(
        model="gpt-5.2",
        input="hi",
    ),
    operation="openai.responses.create",
)
```

## Notes

- `openai_classifier` maps auth, permission, permanent request errors, conflicts, rate limits, server errors, and transient transport failures into redress's current `ErrorClass` values.
- `openai_aware_backoff(...)` is a small ergonomic wrapper around the existing Retry-After-aware strategy pattern with OpenAI-oriented defaults.
- `409` maps to `CONCURRENCY`, not a provider-local fatal bucket.
- `429` responses with `Retry-After` or `x-ratelimit-reset-*` hints populate `Classification.retry_after_s`.

Streaming guidance, full mapping tables, and broader docs integration can expand in later phases.
