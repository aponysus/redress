# Changelog

Release notes are maintained here.

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
