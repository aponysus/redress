# Anthropic

`redress.contrib.anthropic` provides Anthropic-specific retry helpers for the Python SDK.

This module currently exposes:

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
        model="claude-opus-4-7",
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

## Mapping summary

| Anthropic SDK error or status | redress class | Notes |
| --- | --- | --- |
| `AuthenticationError` | `AUTH` | Credentials or auth configuration failed. |
| `PermissionDeniedError` | `PERMISSION` | Caller is authenticated but not allowed. |
| `NotFoundError` | `PERMANENT` | Requested resource or endpoint does not exist. |
| `BadRequestError` | `PERMANENT` | Invalid request payload. |
| `RequestTooLargeError` | `PERMANENT` | Current classifier treats oversized requests as non-retryable. |
| `UnprocessableEntityError` | `PERMANENT` | Request was syntactically valid but rejected as unprocessable. |
| `ConflictError` | `CONCURRENCY` | Current implementation maps `409` to redress concurrency semantics. |
| `RateLimitError` | `RATE_LIMIT` | `Retry-After` and `anthropic-ratelimit-*-reset` hints are preserved when present. |
| `OverloadedError` | `SERVER_ERROR` | Provider overload is treated as a server-side failure. |
| `ServiceUnavailableError` | `SERVER_ERROR` | Retry hint headers are preserved when present. |
| `DeadlineExceededError` | `SERVER_ERROR` | Provider-side deadline failures are treated as upstream server failures. |
| `InternalServerError` | `SERVER_ERROR` | Retry hint headers are preserved when present. |
| `APITimeoutError` | `TRANSIENT` | Transport timeout. |
| `APIConnectionError` | `TRANSIENT` | Connection setup or network failure. |
| `APIResponseValidationError` | `PERMANENT` | SDK could not validate the response shape. |
| `APIStatusError` with `413` | `PERMANENT` | Oversized request fallback when the dedicated exception type is not used. |
| `APIStatusError` with `408` or `425` | `TRANSIENT` | Retry hint headers are propagated into `Classification.retry_after_s`. |
| `APIStatusError` with `500`, `503`, `504`, or `529` | `SERVER_ERROR` | Includes overload-style server failures. |
| `APIStatusError` with `error.type == "overloaded_error"` | `SERVER_ERROR` | Body-based overload mapping, even when the status wrapper is generic. |
| Other `AnthropicError` subclasses | `UNKNOWN` | Fallback bucket until the SDK or classifier is updated. |
| Non-Anthropic exceptions | `default_classifier(...)` | Lets redress handle generic Python and transport errors normally. |

## Streaming

- Retry stream creation, not partial stream consumption. If the request fails before the SDK yields a stream object or before any events are consumed, `anthropic_classifier` and `anthropic_aware_backoff(...)` still apply normally.
- Do not assume redress can resume a message stream after tokens, deltas, or tool events have already been delivered. Automatic replay can duplicate output or side effects.
- Keep the retried unit idempotent. Common pattern: retry the request setup, then consume the stream once outside the retry boundary.
- If you need recovery after a mid-stream disconnect, build explicit application-level restart or resume logic rather than relying on transparent retry.
