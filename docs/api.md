# API reference

## Policies

- `Policy`, `AsyncPolicy`
  - Unified resilience containers; use `Policy(retry=Retry(...))`
  - `.call(func, on_metric=None, on_log=None, operation=None, abort_if=None, sleep=None)`
  - `.execute(func, on_metric=None, on_log=None, operation=None, abort_if=None, sleep=None, capture_timeline=False)`
  - `.context(on_metric=None, on_log=None, operation=None, abort_if=None, sleep=None)`
- `Retry`, `AsyncRetry`
  - Retry components with `result_classifier` support
  - `.call(..., abort_if=None, sleep=None)`, `.execute(..., abort_if=None, sleep=None, capture_timeline=False)`, `.context(..., abort_if=None, sleep=None)`
  - `.from_config(config, classifier=...)`
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
- `http_classifier`, `http_retry_after_classifier`
- `sqlstate_classifier`, `pyodbc_classifier`
- Optional extras: `aiohttp_classifier`, `grpc_classifier`, `boto3_classifier`, `redis_classifier`, `urllib3_classifier`
- `Classification` dataclass for structured classifier outputs

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

## Outcomes

- `RetryOutcome[T]` from `execute()` with attempts, stop_reason, and last error info
- `RetryOutcome.next_sleep_s` when retries are deferred via a sleep handler
- `RetryOutcome.timeline` contains a `RetryTimeline` when `capture_timeline=True`
- `RetryTimeline` with `TimelineEvent` entries (attempt, event, stop_reason, cause, sleep_s, elapsed_s)
- `capture_timeline` accepts `True` or a `RetryTimeline` instance to reuse a collector

## Metrics helpers

- `prometheus_metric_hook(counter)`
- `otel_metric_hook(meter, name="redress_attempts")`
- `redress.contrib.otel.otel_hooks(tracer=None, meter=None)` (spans + metrics)

## Events

- `EventName` enum (`redress.events.EventName`) for hook event constants
- `StopReason` enum is re-exported from `redress.events`

## Sleep handlers

- `SleepDecision` enum (`sleep`, `defer`, `abort`)
