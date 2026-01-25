# Changelog

Release notes are maintained here.

## [1.1.0] - 2026-01-25
### Added
- Unified `Policy`/`Retry` containers (and async variants) with circuit breaker integration.
- `CircuitBreaker`, `CircuitState`, and `CircuitOpenError` plus breaker events.
- Result-based retries via `result_classifier` and structured outcomes via `execute()` / `RetryOutcome`.
- `Classification` + `BackoffContext` for context-aware strategies, plus `retry_after_or` and `http_retry_after_classifier`.
- Attempt lifecycle hooks (`on_attempt_start`, `on_attempt_end`, `AttemptContext`) and cooperative abort (`abort_if`, `AbortRetryError`).
- Sleep handlers (`SleepDecision`, `SleepFn`) to defer retries and surface `next_sleep_s`.
- `EventName` and `StopReason` enums for stable observability, plus `redress.contrib.otel` hooks.

### Changed
- `per_class_max_attempts` now allows `0` to disable retries for a class.
- Missing per-class strategy stops retries with `StopReason.NO_STRATEGY` instead of raising `RuntimeError`.
- The `retry` decorator injects a default strategy only when both `strategy` and `strategies` are omitted.

## [1.0.2] - 2026-01-24
### Fixed
- Use monotonic time for deadline enforcement to avoid wall-clock jumps.
- Propagate cancellation/system-exit exceptions without retries (CancelledError, KeyboardInterrupt, SystemExit).
- Ignore non-HTTP integer args when coercing status in `http_classifier`.

### Added
- `strict_classifier` for classifier logic without name-based heuristics.

### Docs
- Clarify classifier precedence and heuristic guidance.

## [1.0.1] - 2026-01-23
### Fixed
- Preserve original tracebacks when retries stop (permanent failures, caps, deadlines).

### Docs
- Move changelog to the repository root.

## [1.0.0] - 2025-12-24
### Added
- 1.0 release and project rename to `redress`.

## [0.2.2] - 2025-11-24
### Added
- bugfixes and docs updates

## [0.2.1] - 2025-11-24
### Added
- bugfixes and docs updates

## [0.2.0] - 2025-11-23
### Added
- `retry` decorator for wrapping sync and async callables with RetryPolicy/AsyncRetryPolicy.
- Decorator usage example script and README updates.
- Usage docs covering decorator-based retries.

## [0.1.0] - 2025-11-23
### Added
- Initial functional version of `redress` with error classification, RetryPolicy with deadlines/per-class limits/hooks, jitter strategies, and metrics/logging adapters.
