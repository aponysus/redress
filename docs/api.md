# API reference (high-level)

## Policies

- `RetryPolicy`, `AsyncRetryPolicy`
  - `.call(func, on_metric=None, on_log=None, operation=None)`
  - `.context(on_metric=None, on_log=None, operation=None)`
  - `.from_config(config, classifier=...)`

## Decorator

- `retry`
  - Defaults: `classifier=default_classifier`, `strategy=decorrelated_jitter(max_s=5.0)`
  - Works on sync and async callables

## Classifiers

- `default_classifier`
- `http_classifier`, `sqlstate_classifier`, `pyodbc_classifier` (contrib)

## Strategies

- `decorrelated_jitter`
- `equal_jitter`
- `token_backoff`

## Errors

- `ErrorClass` enum
- Marker exceptions: `PermanentError`, `RateLimitError`, `ConcurrencyError`

## Metrics helpers

- `prometheus_metric_hook(counter)`
- `otel_metric_hook(meter, name="redress_attempts")`
