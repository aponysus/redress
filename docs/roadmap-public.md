# Public Roadmap

!!! note
    This roadmap is directional, not a promise. Dates are targets and may shift.

## v1.0.x Hardening (Maintenance)

Focus: correctness and reliability fixes for the existing retry engine.

- Use monotonic time for deadlines.
- Do not retry cancellation/system-exiting exceptions.
- Tighten HTTP status coercion in `http_classifier`.
- Clarify classifier heuristics and safety guidance in docs.

## v1.1 (Q1 2026) Policy, Breakers, and Practical Ergonomics

Focus: a coherent execution model plus integration ergonomics that avoid bespoke glue.

- Introduce unified `Policy` + `Retry` components (sync + async), keeping `RetryPolicy` as convenient sugar.
- Add a first-class `CircuitBreaker` with state transitions and events.
- Result-based retries (`result_classifier`) for HTTP/SDK responses without forcing exceptions.
- Classification context and strategy integration (classifiers can emit hints; strategies can consume them).
- Retry-After support as a built-in strategy helper.
- Cleaner outcome surface: stable stop reasons and typed terminal outcomes (attempts/last class).
- Timeline capture (optional) for per-attempt debugging without custom hooks.
- Observability improvements and an OpenTelemetry contrib hook.
- Docs refresh with end-to-end recipes (HTTP calls, worker loops, graceful shutdown).

## v1.2 (Q2 2026) Built-in Classifiers and Recipes

Focus: reduce bespoke wiring for common stacks.

- Built-in classifiers for common libraries (aiohttp, grpc, boto3/botocore, redis, etc.) via extras.
- Classifier authoring guidance and integration recipes.
- Additional small strategy helpers driven by real-world patterns.

## v1.3 (Q3 2026) Advanced Patterns and Testability

Focus: production guardrails and deterministic behavior.

- Retry budgets to prevent retry storms.
- Testing utilities for deterministic retries.
- Per-attempt timeouts in addition to overall deadlines.
- Injectable sleeper / before-sleep hook to integrate with leases and external schedulers.

## v1.4+ (Q4 2026+) Ecosystem Expansion

Focus: optional integrations and higher-level execution models.

- Framework integrations (Django, Flask, Celery, FastAPI).
- Contrib observability modules (Prometheus, Datadog, Sentry).
- Non-blocking / externally scheduled retry execution (advanced).
- Experimental hedging support (async-first).

## Ongoing Documentation

- Migration guides (Tenacity, Backoff).
- Performance tuning and troubleshooting guides.
