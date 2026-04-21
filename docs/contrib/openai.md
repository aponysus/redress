# OpenAI

`redress.contrib.openai` provides OpenAI-specific retry helpers for the Python SDK.

This module currently exposes:

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

## Mapping summary

| OpenAI SDK error or status | redress class | Notes |
| --- | --- | --- |
| `AuthenticationError` | `AUTH` | Credentials or auth configuration failed. |
| `PermissionDeniedError` | `PERMISSION` | Caller is authenticated but not allowed. |
| `NotFoundError` | `PERMANENT` | Resource or endpoint does not exist for the request. |
| `BadRequestError` | `PERMANENT` | Invalid request payload. |
| `UnprocessableEntityError` | `PERMANENT` | Request was syntactically valid but rejected as unprocessable. |
| `ConflictError` | `CONCURRENCY` | Current implementation maps `409` to redress concurrency semantics. |
| `RateLimitError` | `RATE_LIMIT` | If `body.code == "insufficient_quota"`, this maps to `PERMANENT` instead. |
| `InternalServerError` | `SERVER_ERROR` | `Retry-After` hints are preserved when present. |
| `APITimeoutError` | `TRANSIENT` | Transport timeout. |
| `APIConnectionError` | `TRANSIENT` | Connection setup or network failure. |
| `APIResponseValidationError` | `PERMANENT` | SDK could not validate the response shape. |
| `APIStatusError` with `408` or `425` | `TRANSIENT` | Retry hint headers are propagated into `Classification.retry_after_s`. |
| `APIStatusError` with `500`, `502`, `503`, or `504` | `SERVER_ERROR` | Retry hint headers are propagated into `Classification.retry_after_s`. |
| Other `OpenAIError` subclasses | `UNKNOWN` | Fallback bucket until the SDK or classifier is updated. |
| Non-OpenAI exceptions | `default_classifier(...)` | Lets redress handle generic Python and transport errors normally. |

## Streaming

- Retry stream creation, not partial stream consumption. If the call fails before the SDK yields a stream object or before any events are consumed, `openai_classifier` and `openai_aware_backoff(...)` still work normally.
- Do not assume redress can transparently resume a stream after tokens or tool events have already been emitted. Once output has been observed, replay can duplicate content or side effects.
- If you need retry around a streaming workflow, keep the retried unit idempotent. Typical pattern: retry the request setup, then consume the returned stream exactly once outside the retry boundary.
- If your application must recover from mid-stream interruption, handle that at the application layer with explicit resume or restart semantics rather than automatic exception replay.
