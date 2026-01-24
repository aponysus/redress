# API reference (high-level)

## Policies

- `Policy`, `AsyncPolicy`
  - Unified resilience containers; use `Policy(retry=Retry(...))`
  - `.call(func, on_metric=None, on_log=None, operation=None, abort_if=None)`
  - `.context(on_metric=None, on_log=None, operation=None, abort_if=None)`
- `Retry`, `AsyncRetry`
  - Retry components with `result_classifier` support
  - `.call(..., abort_if=None)`, `.context(..., abort_if=None)`, `.from_config(config, classifier=...)`
- `RetryPolicy`, `AsyncRetryPolicy`
  - Backward-compatible sugar for `Policy(retry=Retry(...))`
- `CircuitBreaker`
  - State machine with open/half-open/closed transitions
  - Use with `Policy(circuit_breaker=...)`
- `CircuitState` enum

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
- `CircuitOpenError` fail-fast error when breaker is open
- `StopReason` enum
- `RetryExhaustedError` terminal error (result-based exhaustion)
- `AbortRetryError` cooperative abort signal (alias: `AbortRetry`)
- Marker exceptions: `PermanentError`, `RateLimitError`, `ConcurrencyError`

## Metrics helpers

- `prometheus_metric_hook(counter)`
- `otel_metric_hook(meter, name="redress_attempts")`
- `redress.contrib.otel.otel_hooks(tracer=None, meter=None)` (spans + metrics)
