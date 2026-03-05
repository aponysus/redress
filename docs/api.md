# API reference

## Policies

- `Policy`, `AsyncPolicy`
  - Unified resilience containers; use `Policy(retry=Retry(...))`
  - `.call(func, on_metric=None, on_log=None, operation=None, abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None)`
  - `.execute(func, on_metric=None, on_log=None, operation=None, abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None, capture_timeline=False)`
  - `.context(on_metric=None, on_log=None, operation=None, abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None)`
- `Retry`, `AsyncRetry`
  - Retry components with `result_classifier` support
  - Support per-attempt timeouts via `attempt_timeout_s`
  - `.call(..., abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None)`
  - `.execute(..., abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None, capture_timeline=False)`
  - `.context(..., abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None)`
  - `.from_config(config, classifier=...)`
- `RetryPolicy`, `AsyncRetryPolicy`
  - Backward-compatible sugar for `Policy(retry=Retry(...))`
  - `.call(..., abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None)`
  - `.execute(..., abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None, capture_timeline=False)`
  - `.context(..., abort_if=None, sleep=None, before_sleep=None, sleeper=None, on_attempt_start=None, on_attempt_end=None)`
- `CircuitBreaker`
  - State machine with open/half-open/closed transitions
  - `failure_threshold=5` failures in `window_s=60.0` seconds to open
  - `recovery_timeout_s=30.0` before half-open probe
  - `trip_on` set of ErrorClass values that count (default: TRANSIENT, SERVER_ERROR)
  - `class_thresholds` per-class override thresholds
  - `clock` optional monotonic clock override
  - Use with `Policy(circuit_breaker=...)`
- `CircuitState` enum
## Budgets

- `Budget(max_retries, window_s)` for shared retry limits across policies

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
- `adaptive`
- `BackoffContext` for context-aware strategy functions

## Errors

- `ErrorClass` enum
- `CircuitOpenError` fail-fast error when breaker is open
- `StopReason` enum
- `RetryExhaustedError` terminal error (result-based exhaustion)
- `AbortRetryError` cooperative abort signal (alias: `AbortRetry`)
- Marker exceptions: `PermanentError`, `RateLimitError`, `ConcurrencyError`, `ServerError`

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

## Contrib integrations

- `redress.contrib.asgi.retry_middleware(...)` (generic Starlette-style ASGI middleware helper)
- `redress.contrib.asgi.default_operation(request)` / `scope_operation(request)` (`METHOD + scope["path"]`)
- `redress.contrib.asgi.is_idempotent_request(request)` (HTTP idempotency guard helper)
- `redress.contrib.fastapi.retry_middleware(...)` (FastAPI/Starlette middleware helper)
- `redress.contrib.fastapi.default_operation(request)` (method + route path)
- `redress.contrib.httpx.RetryingHttpxClient(client, policy, ...)` (sync wrapper class)
- `redress.contrib.httpx.AsyncRetryingHttpxClient(client, policy, ...)` (async wrapper class)
- `redress.contrib.httpx.request_with_retry(...)` (sync request wrapper)
- `redress.contrib.httpx.arequest_with_retry(...)` (async request wrapper)
- `redress.contrib.httpx.default_result_classifier(response)` (429/408/409/5xx mapper with Retry-After support)
- `redress.contrib.httpx.is_idempotent_method(method)` (HTTP method guard helper)
- `redress.contrib.grpc.unary_unary_client_interceptor(...)` (sync unary-unary client interceptor factory)
- `redress.contrib.grpc.aio_unary_unary_client_interceptor(...)` (async unary-unary client interceptor factory)
- `redress.contrib.grpc.default_operation(call_details)` (operation tag from RPC method path)
- `redress.contrib.grpc.rpc_service_name(call_details)` / `rpc_method_name(call_details)` (RPC name helpers)
- Note: ASGI contrib targets `request/call_next` middleware shape, not raw `(scope, receive, send)`.

## Events

- `EventName` enum (`redress.events.EventName`) for hook event constants
- `StopReason` enum is re-exported from `redress.events`

## Sleep handlers

- `SleepDecision` enum (`sleep`, `defer`, `abort`)
- `SleepFn` for custom sleep handling (decide sleep/defer/abort)
- `BeforeSleepHook` / `AsyncBeforeSleepHook` run right before an actual sleep
- `SleeperFn` / `AsyncSleeperFn` replace the actual sleep call

## Testing utilities

Available under `redress.testing`:

- `DeterministicStrategy`, `instant_retries`, `no_retries`
- `RecordingPolicy`, `FakePolicy`
- `FakeCircuitBreaker`, `BreakerDecision`
