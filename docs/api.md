# API reference (high-level)

## Policies

- `RetryPolicy`, `AsyncRetryPolicy`
  - Accept `result_classifier` for result-based retries
  - `.call(func, on_metric=None, on_log=None, operation=None)`
  - `.context(on_metric=None, on_log=None, operation=None)`
  - `.from_config(config, classifier=...)`

## Decorator

- `retry`
  - Defaults: `classifier=default_classifier`, `strategy=decorrelated_jitter(max_s=5.0)`
  - Works on sync and async callables

## Classifiers

- `default_classifier`
- `strict_classifier`
- `http_classifier`, `sqlstate_classifier`, `pyodbc_classifier` (contrib)
- `Classification` dataclass for structured classifier outputs
- `http_retry_after_classifier` for Retry-After extraction

## Strategies

- `decorrelated_jitter`
- `equal_jitter`
- `token_backoff`
- `retry_after_or`
- `BackoffContext` for context-aware strategy functions

## Errors

- `ErrorClass` enum
- `StopReason` enum
- `RetryExhaustedError` terminal error (result-based exhaustion)
- Marker exceptions: `PermanentError`, `RateLimitError`, `ConcurrencyError`

## Metrics helpers

- `prometheus_metric_hook(counter)`
- `otel_metric_hook(meter, name="redress_attempts")`
