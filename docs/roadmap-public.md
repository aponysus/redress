# Public Roadmap

!!! note
    This roadmap is directional, not a promise. Dates are targets and may shift.

## Delivered through v1.2

Recent releases established the current execution model and integration surface:

- `Policy` / `Retry` and `AsyncPolicy` / `AsyncRetry` as the canonical API
- `RetryPolicy` / `AsyncRetryPolicy` as backward-compatible sugar
- Circuit breakers with state transitions and events
- Result-based retries and structured `Classification`
- Context-aware strategies and Retry-After-aware helpers
- Stable stop reasons and `RetryOutcome`
- Optional timeline capture
- Retry budgets
- Per-attempt timeouts
- Injectable sleeper / before-sleep hooks
- Built-in extras for common stacks
- Contrib integrations for HTTP clients, ASGI/FastAPI, gRPC, Celery, and observability backends

## Current maintenance focus

Focus: correctness, docs clarity, and keeping the existing API surface coherent.

- Reliability fixes in the retry engine and integrations
- Documentation cleanup around the unified policy model
- Better migration guidance for users coming from retry-only libraries
- Performance tuning and troubleshooting guidance

## Next expansion areas

### Framework and ecosystem integrations

- Additional framework integrations where they simplify adoption materially
- More turnkey examples around queue/worker and service patterns
- Tightening contrib contracts and compatibility expectations as the surface grows

### Advanced execution models

- Non-blocking / externally scheduled retry execution patterns
- Experimental hedging support (async-first)

## Ongoing Documentation

- Migration guides (Tenacity, Backoff, retry-only wrappers to `Policy`)
- Performance tuning and troubleshooting guides
