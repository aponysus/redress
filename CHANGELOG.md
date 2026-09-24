# Changelog

Release notes are maintained here.

## [Unreleased]

### Fixed
- Isolated ordinary exceptions from `on_attempt_start` and `on_attempt_end` across sync/async execution and `call()`/`execute()`, including policies without retries. Observer failures no longer repeat successful operations, replace operation failures, or affect retry budgets and circuit-breaker outcomes. Cancellation and process-exit exceptions still propagate.

## [1.4.2] - 2026-09-24

Version 1.4.1 was tagged with incorrect package metadata and was not published
to PyPI. Its fixes and documentation are included in 1.4.2; the existing
`v1.4.1` tag is retained unchanged.

### Fixed
- Sync and async retries now stop at the final allowed failed attempt without computing backoff, consuming a retry budget token, emitting a `retry` event, or invoking sleep hooks and handlers. This applies to both exception-based and result-based failures through `call()` and `execute()`.
- Global attempt exhaustion now reports `MAX_ATTEMPTS_GLOBAL` instead of being replaced by budget exhaustion or a sleep handler's defer/abort decision. Existing classification and deadline stop conditions retain precedence.

### Changed
- Updated the PyPI publisher to support core metadata 2.5 and added strict Twine metadata validation to CI and release checks.
- Added release consistency gates for tags, package and lockfile versions, changelog entries, and built wheel/sdist metadata. Publishing now fails on existing artifacts and creates the GitHub release only after a successful PyPI upload.

### Docs
- Added dedicated migration guides for Tenacity and Backoff, plus performance tuning and troubleshooting guides, linked from the docs index and navigation.
- Clarified attempt limits, timeout behavior, retry budgets, and terminal outcomes, with executable examples checked against the current APIs.

Retry telemetry may contain fewer `retry` events after this fix: the final failed attempt emits exhaustion without an extra retry event. No public API changes are required to upgrade.

## [1.4.0] - 2026-04-21
### Added
- New provider-specific contrib integrations for OpenAI and Anthropic via `redress.contrib.openai` and `redress.contrib.anthropic`.
- OpenAI and Anthropic classifier helpers (`openai_classifier`, `anthropic_classifier`) that map SDK exceptions into redress `ErrorClass` values and preserve provider retry hints.
- OpenAI- and Anthropic-aware backoff helpers (`openai_aware_backoff(...)`, `anthropic_aware_backoff(...)`) built on top of `retry_after_or(...)`.
- Optional dependency groups for `openai` and `anthropic`.
- Drift/conformance tests against the installed OpenAI and Anthropic SDK exception hierarchies.

### Changed
- CI now installs the OpenAI and Anthropic extras so provider contrib coverage runs in the main test matrix.
- Public landing-page copy now foregrounds the provider contrib modules and current integration surface instead of older extras-first positioning.


## [1.3.0] - 2026-03-20
### Added
- New contrib integrations for `aiohttp`, `requests`, and Celery.
- New observability contrib modules for Prometheus, Datadog, and Sentry.
- Optional dependency groups for `requests`, `celery`, `prometheus`, `datadog`, and `sentry`.
- Additional tests across contrib and extras modules, including targeted coverage for `pyodbc` and `grpc` extras.

### Docs
- Repositioned `Policy(retry=Retry(...))` as the canonical API in Getting Started and README.
- Refreshed design notes and public roadmap to match the shipped unified policy model and current roadmap state.
- Clarified contrib-module stability guidance in the API reference.
- Restructured docs IA around `Core guide`, `Concepts`, and `Recipes`, with clearer page framing and improved nav hierarchy styling.

## [1.2.0] - 2026-02-02
### Added
- Optional classifier helpers via extras: `aiohttp`, `grpc`, `boto3/botocore`, `redis`, `urllib3`, and `pyodbc`.
- Shared retry budgets (`Budget`) with `BUDGET_EXHAUSTED` stop reason/event for backpressure.
- Testing utilities under `redress.testing` (DeterministicStrategy, instant/no retries, FakePolicy, RecordingPolicy, FakeCircuitBreaker).
- Per-attempt timeouts (`attempt_timeout_s`) for Retry/AsyncRetry; `TimeoutError` defaults to TRANSIENT.
- Injectable sleeper (`SleeperFn`) and `before_sleep` hooks for sync/async retries.
- Adaptive backoff strategy wrapper (`adaptive`) for failure-rate-sensitive backoff.

### Docs
- Added testing guide, worker/queue recipe, and comparison page.
- Expanded production checklist and budget backpressure guidance.

## [1.1.0] - 2026-01-25
### Added
- Unified `Policy`/`Retry` containers (and async variants) with circuit breaker integration.
- `CircuitBreaker`, `CircuitState`, and `CircuitOpenError` plus breaker events.
- Result-based retries via `result_classifier` and structured outcomes via `execute()` / `RetryOutcome`.
- `Classification` + `BackoffContext` for context-aware strategies, plus `retry_after_or` and `http_retry_after_classifier`.
- Attempt lifecycle hooks (`on_attempt_start`, `on_attempt_end`, `AttemptContext`) and cooperative abort (`abort_if`, `AbortRetryError`).
- Sleep handlers (`SleepDecision`, `SleepFn`) to defer retries and surface `next_sleep_s`.
- `EventName` and `StopReason` enums for stable observability, plus `redress.contrib.otel` hooks.
- Optional timeline capture on `execute()` via `RetryOutcome.timeline`.

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
