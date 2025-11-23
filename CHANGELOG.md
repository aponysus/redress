# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2025-11-23
### Added
- `retry` decorator for wrapping sync and async callables with RetryPolicy/AsyncRetryPolicy.
- Decorator usage example script (`examples/decorator_retry.py`) and README updates.
- Usage docs covering decorator-based retries.

## [0.1.0] - 2025-11-23
### Added
- Initial functional version of `reflexio` with:
  - Error classification (including auth/permission)
  - RetryPolicy with deadline, per-class limits, and observability hooks
  - Jitter-based backoff strategies
  - Metrics/logging adapters and docs
