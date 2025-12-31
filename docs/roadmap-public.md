# Public Roadmap

!!! note
    This roadmap is directional, not a promise. Dates are targets and may shift.

## v1.0.x Hardening (Maintenance)

Focus: correctness and reliability fixes for the existing retry engine.

- Preserve original tracebacks when retries stop.
- Use monotonic time for deadlines.
- Do not retry cancellation/system-exiting exceptions.
- Tighten HTTP status coercion in `http_classifier`.
- Clarify classifier heuristics in documentation.

## v1.1 (Q1 2026) Unified Policy and Circuit Breakers

Focus: a unified resilience model and circuit breaker integration.

- Introduce `Policy` and `Retry` components (plus async variants).
- Add a first-class `CircuitBreaker` with state transitions and events.
- Improve observability with new metrics and OpenTelemetry hooks.
- Refresh docs with migration guides and updated examples.

## v1.2 (Q2 2026) Classification Refinements

Focus: richer classification without expanding error classes.

- Add `Classification` context support for classifiers and strategies.
- Provide a Retry-After aware strategy.
- Add built-in classifiers for common libraries (aiohttp, grpc, boto3, redis).
- Publish docs for classification context and classifier authoring.

## v1.3 (Q3 2026) Advanced Patterns

Focus: production hardening and test tooling.

- Retry budgets to prevent retry storms.
- Testing utilities for deterministic retries.
- Per-attempt timeouts in addition to overall deadlines.
- Adaptive strategies (lower priority, based on demand).

## v1.4+ (Q4 2026+) Ecosystem Expansion

Focus: integrations and optional contrib modules.

- Framework integrations (Django, Flask, Celery, FastAPI).
- Contrib observability modules (Prometheus, Datadog, Sentry).
- Experimental hedging support (async-first).

## Ongoing Documentation

- Migration guides (Tenacity, Backoff).
- Performance tuning and troubleshooting guides.
