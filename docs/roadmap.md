# Redress Roadmap

Post-1.0 development roadmap for the redress Python resilience library.

## Versioning Strategy

- **1.x releases**: Backward-compatible feature additions
- **Semantic versioning**: MAJOR.MINOR.PATCH
- **Deprecation policy**: Deprecate in x.y, remove in x.(y+2) at earliest

---

## Design Alignment with recourse

redress (Python) and [recourse](https://github.com/aponysus/recourse) (Go) are sibling resilience libraries sharing core design principles:

| Concept | recourse (Go) | redress (Python) |
|---------|---------------|------------------|
| Unified policy | `policy.EffectivePolicy` | `Policy` (v1.1+) |
| Retry component | Embedded in policy | `Retry` |
| Circuit breaker | `policy.CircuitPolicy` | `CircuitBreaker` |
| Budgets | `budget.Budget` | `Budget` (v1.3+) |
| Hedging | `policy.HedgePolicy` | Contrib (deferred, async-first) |
| Classifiers | `classify.Classifier` | `Classifier` |
| Timeline capture | `observe.Timeline` + `observe.RecordTimeline` | `observe.Timeline` / `RetryReport` (v1.1+) |
| Streaming telemetry | `observe.Observer` | `on_metric` / `on_log` hooks (v1.0+) |

**Key divergence:** redress uses standalone policy objects; recourse uses policy keys with a `PolicyProvider` for centralized configuration. This is intentional — Python services tend toward explicit configuration, while Go services often benefit from centralized policy management.

---

## v1.0.x — Hardening & Reliability

**Theme:** Strengthen the existing retry engine without changing the mental model

**Target:** Q1 2026 (ongoing patch releases)

**Deliverables:**
- Monotonic deadlines (avoid wall-clock drift).
- Do not retry cancellation/system-exiting exceptions.
- Tighten HTTP status coercion in `http_classifier`.
- Clarify default classifier heuristics and safety guidance in docs.

---

## v1.1 — Unified Policy Model, Circuit Breakers, and Integration Ergonomics

**Theme:** One coherent execution model plus ergonomics that reduce bespoke glue in real services

**Target:** Q1 2026

### Architectural Change: Unified Policy Model

The addition of circuit breakers motivates a broader architectural shift. Rather than bolting features onto `RetryPolicy`, v1.1 introduces a **unified `Policy` model** where retry is one optional component among several.

This aligns with the architecture proven in [recourse](https://github.com/aponysus/recourse) (the Go resilience library), where policies are containers for multiple resilience components.

**Key changes:**
- New `Policy` class as the unified resilience container
- New `Retry` class to hold retry-specific configuration
- `RetryPolicy` becomes sugar for `Policy(retry=Retry(...))`
- Backward compatibility — existing code continues to work

**Proposed API:**
```python
from redress import Policy, Retry, CircuitBreaker
from redress import default_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        strategies={...},              # Per-class overrides
        max_attempts=5,
        max_unknown_attempts=2,
        deadline_s=60,

        # v1.1 ergonomics:
        result_classifier=None,         # Optional (result-based retries)
        abort_if=None,                 # Optional (cooperative abort)
    ),
    circuit_breaker=CircuitBreaker(
        failure_threshold=5,
        window_s=60,
        recovery_timeout_s=30,
        trip_on={ErrorClass.TRANSIENT, ErrorClass.SERVER_ERROR},
    ),
)

result = policy.call(my_op, operation="fetch_user")
```

**Execution order within Policy (conceptual):**
```
0. Cooperative abort check (if configured)
1. Circuit breaker check (fail fast if open)
2. Retry loop (if retry configured)
   a. Execute operation
   b. Classify exception/result into ErrorClass (+ optional metadata)
   c. If retryable, compute backoff and retry
3. Record final outcome for circuit breaker (one outcome per operation, post-retry)
4. Expose outcome via hooks and typed outcome surface (if requested)
```

### Features

#### 1. Circuit Breaker Integration
**Priority:** High | **Effort:** Large

Circuit breakers prevent cascading failures by failing fast when a downstream service is unhealthy.

**Design considerations:**
- Per-class circuit breaking (leverage existing ErrorClass taxonomy)
- State transitions: closed → open → half-open → closed
- Configurable thresholds, windows, and recovery probes
- Thread-safe for sharing across policies
- Async-safe (no blocking)
- Breaker wraps the retry executor: record one outcome per operation (post-retry), not per attempt

**CircuitBreaker API:**
```python
from redress import CircuitBreaker, ErrorClass

breaker = CircuitBreaker(
    failure_threshold=5,        # Failures before opening
    window_s=60,                # Sliding window for failure counting
    recovery_timeout_s=30,      # Time in open state before half-open
    trip_on={ErrorClass.TRANSIENT, ErrorClass.SERVER_ERROR},

    # Optional: per-class thresholds
    class_thresholds={
        ErrorClass.RATE_LIMIT: 3,
    },
)
```

**Observability events to add:**
- `circuit_opened`
- `circuit_half_open`
- `circuit_closed`
- `circuit_rejected`

#### 2. Result-Based Retries
**Priority:** High | **Effort:** Medium

Support retry decisions based on returned values (e.g., HTTP 503 responses) without forcing exceptions.

**Shape:**
- Optional `result_classifier(result) -> None | ErrorClass | Classification`
- Preserve exception-based behavior by default
- Ensure terminal outcomes reflect the last failure (result vs exception)

#### 3. Classification Context (Metadata Propagation)
**Priority:** High | **Effort:** Medium

Allow classifiers to return a structured classification that carries hints needed by strategies and observability (e.g., Retry-After).

**Shape:**
- Classifier can return `ErrorClass` (backward compatible) or `Classification`
- `Classification` holds the `ErrorClass` plus optional typed fields (e.g., `retry_after_s`) and safe metadata

#### 4. Strategy Context (BackoffContext)
**Priority:** High | **Effort:** Medium

Allow strategies to optionally consume classification metadata and time remaining.

**Shape:**
- Preserve legacy strategy signature
- Add an optional context-aware signature receiving `BackoffContext`

#### 5. Retry-After Aware Strategy
**Priority:** Medium | **Effort:** Small

Built-in strategy helper that honors Retry-After when present and falls back to jitter otherwise.

```python
from redress.strategies import retry_after_or, decorrelated_jitter

strategy = retry_after_or(decorrelated_jitter(max_s=60.0))
```

#### 6. Outcome Surface (StopReason + Typed Terminal Outcome)
**Priority:** High | **Effort:** Medium

Reduce integration boilerplate by exposing stop reasons and attempt counts without requiring consumers to interpret string hook events.

**Deliverables:**
- Stable `StopReason` enum (terminal causes)
- Typed terminal error / outcome object carrying:
  - `stop_reason`, `attempts`, `last_class`, and last exception/result (as appropriate)

#### 7. Cooperative Abort
**Priority:** Medium | **Effort:** Small

First-class cooperative abort support for worker shutdown/drain flows.

**Shape:**
- `AbortRetry` exception and/or `abort_if` predicate
- Emits `StopReason.ABORTED`

#### 8. Timeline Capture (Retry Report)
**Priority:** Medium | **Effort:** Medium

Optional per-call timeline capture for debugging and tests without bespoke hooks.

**Shape:**
- `observe.Timeline` / `RetryReport` with per-attempt records (attempt, class, backoff, elapsed)
- Opt-in capture API; keep default overhead near-zero
- Safe by default: avoid retaining full exception objects unless explicitly requested

#### 9. OpenTelemetry Contrib Module
**Priority:** Medium | **Effort:** Medium

Contrib module for OTEL span events and metrics for retries and circuits.

```python
from redress.contrib.otel import otel_hooks

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
    **otel_hooks(),
)
```

#### 10. Structlog Integration Example
**Priority:** Medium | **Effort:** Small

Documentation and snippet showing structlog integration.

```python
import structlog
from redress import RetryPolicy

logger = structlog.get_logger()

def structured_log_hook(event, attempt, sleep_s, tags):
    logger.info(
        "retry_event",
        event=event,
        attempt=attempt,
        sleep_seconds=sleep_s,
        **tags,
    )
```

#### 11. Comparison Documentation
**Priority:** Medium | **Effort:** Small

Docs page: "Redress vs. Alternatives" (Tenacity, Backoff, etc.)

#### 12. Sharp-Edge Ergonomics
**Priority:** High | **Effort:** Small

Small changes that prevent runtime surprises and reduce glue:
- Missing-strategy behavior is deterministic and does not mask the underlying exception.
- `per_class_max_attempts=0` disables retries for that class.
- Decorator defaults match policy semantics.
- Terminal outcomes distinguish global vs per-class exhaustion.

---

## v1.2 — Built-in Classifiers & Integration Recipes

**Theme:** Reduce bespoke wiring for common stacks

**Target:** Q2 2026

### Features

#### 1. Additional Built-in Classifiers
**Priority:** High | **Effort:** Medium

Expand classifier coverage for common libraries via extras.

| Classifier | Library | Notes |
|------------|---------|-------|
| `aiohttp_classifier` | aiohttp | Client and server errors |
| `grpc_classifier` | grpcio | gRPC status codes |
| `boto3_classifier` | boto3/botocore | AWS throttling, service unavailable |
| `redis_classifier` | redis-py | Connection errors, busy loading |

**Implementation approach:**
- Optional dependencies (extras)
- `pip install redress[boto3]` installs boto3 classifier
- Classifiers fail gracefully if dependency not installed

#### 2. Recipe Pack (HTTP + DB + Workers)
**Priority:** Medium | **Effort:** Medium

Publish reference recipes that compose:
- policy definition + reuse patterns
- classification + Retry-After patterns
- observability wiring (metrics + tracing)
- safe tag guidance

#### 3. Classifier Authoring Guidance (Expanded)
**Priority:** Medium | **Effort:** Small

Practical guidance on building safe classifiers:
- precedence rules
- what to log/tag (and what not to)
- avoiding brittle heuristics

---

## v1.3 — Advanced Patterns

**Theme:** Production guardrails and deterministic behavior

**Target:** Q3 2026

### Features

#### 1. Retry Budgets
**Priority:** High | **Effort:** Medium

Retry budgets prevent retry storms by limiting aggregate retry work across operations.

#### 2. Testing Utilities
**Priority:** High | **Effort:** Medium

Deterministic testing tools:
- seeded jitter
- fake clock/sleeper
- assertion helpers for timelines/outcomes

#### 3. Per-Attempt Timeouts
**Priority:** Medium | **Effort:** Medium

Support per-attempt timeouts in addition to overall deadlines.

#### 4. Injectable Sleeper / Before-Sleep Hook
**Priority:** Medium | **Effort:** Medium

Allow custom sleep functions and a `before_sleep` callback to integrate with leases and external schedulers.

#### 5. Adaptive Strategies
**Priority:** Low | **Effort:** Large

Demand-driven adaptive strategies (deprioritized; ship only if adoption needs it).

---

## v1.4+ — Ecosystem Expansion

### Focus Areas

#### Framework Integrations
- Django
- Flask
- Celery
- FastAPI

#### Additional Contrib Modules
- Prometheus metrics hooks
- Datadog, Sentry
- Logging integrations

#### Deferred / Advanced: Externally Scheduled Retry Execution
Non-blocking "step" execution for systems that schedule retries in a DB/queue rather than sleeping.

#### Deferred / Contrib: Hedging (Async-first, Experimental)

---

## Documentation Roadmap

### v1.0.x Documentation
- [ ] Classifier heuristics and safety guidance (cardinality, logging)

### v1.1 Documentation
- [ ] Unified Policy model guide
- [ ] Migration guide: RetryPolicy → Policy
- [ ] Circuit breaker concepts and usage
- [ ] Result-based retries guide
- [ ] Classification context + Retry-After patterns
- [ ] Stop reasons and typed terminal outcomes
- [ ] Timeline capture / retry report guide
- [ ] Structlog integration snippet
- [ ] OpenTelemetry setup guide
- [ ] Comparison page: "Redress vs. Alternatives"
- [ ] Update examples (HTTP downstream call, worker loop, graceful shutdown)

### v1.2 Documentation
- [ ] Built-in classifiers (aiohttp/grpc/boto3/redis) and extras packaging
- [ ] Classifier authoring guide (expanded)
- [ ] Integration recipes/cookbook

### v1.3 Documentation
- [ ] Retry budgets and backpressure
- [ ] Testing guide
- [ ] Per-attempt timeouts
- [ ] Production checklist (expanded)

### Ongoing Documentation
- [ ] Migration guide: "Migrating from tenacity"
- [ ] Migration guide: "Migrating from backoff"
- [ ] Performance tuning guide
- [ ] Troubleshooting guide

---

## GitHub Project Structure

### Labels

```
type/feature         — New functionality
type/enhancement     — Improvements to existing features
type/documentation   — Documentation only
type/bug             — Bug fixes
type/contrib         — Contrib modules (OTEL, frameworks)
type/testing         — Testing utilities

priority/high        — Required for milestone
priority/medium      — Should have for milestone
priority/low         — Nice to have

effort/small         — < 1 day
effort/medium        — 1-3 days
effort/large         — 1+ week

status/needs-design  — Requires design discussion
status/ready         — Ready for implementation
status/in-progress   — Currently being worked on
status/review        — Ready for review
```

### Milestones

- `v1.0.x` — Hardening & Reliability
- `v1.1.0` — Unified Policy, Breaker, and Ergonomics
- `v1.2.0` — Built-in Classifiers & Recipes
- `v1.3.0` — Advanced Patterns
- `v1.4.0` — Ecosystem Expansion
- `backlog` — Good ideas, not yet scheduled

---

## Community & Feedback

### Pre-Implementation Feedback

For major API changes (Policy model, breaker, budgets), gather feedback:
- GitHub Discussions
- Example PRs in `labs/`
- "Design memo" markdown in `docs/design/`

### Adoption Tracking

Monitor adoption through:
- GitHub stars/forks
- PyPI download stats
- GitHub issues/discussions
- Community mentions

### Feature Requests

Track feature requests in GitHub Discussions until triaged and accepted into the roadmap.

---

## Open Questions

### Circuit Breaker Design
- Should circuit breakers be per-ErrorClass or global? (Leaning: global with per-class thresholds)
- Should half-open state use a probe request or percentage of traffic?
- Should circuit state be exposed via the observability hook or separate callback?

### Classification Context
- Should classification metadata be immutable for the life of an attempt?
- Should strategies be able to write back to classification metadata?

### Timeline Capture
- Should the default timeline store exception objects or only safe fields (type/message)?
- Should timeline capture be opt-in per call, per policy, or both?

### Scheduling
- Do we want a first-class "step" API for externally scheduled retries, or keep it as a contrib helper?

### Retry Budgets
- Should budget exhaustion raise a specific exception or return a result type?
- Budget exhaustion behavior: fail-open or fail-closed?

### Naming
- `Policy` vs `ResiliencePolicy` for the unified class?

---

## Changelog

| Date | Change |
|------|--------|
| 2024-12-24 | Initial roadmap created |
| 2024-12-24 | Decided: Unified `Policy` model for v1.1 (aligned with recourse architecture) |
| 2026-01-24 | Updated roadmap: pulled classification context + Retry-After into v1.1; added timeline capture, typed outcomes, cooperative abort, and scheduling hooks |
| — | v1.0.0 released 🎉 |
