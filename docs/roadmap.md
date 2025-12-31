# Redress Roadmap

Post-1.0 development roadmap for the redress Python retry library.

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
| Observability | `observe.Timeline` | `on_metric` / `on_log` hooks |

**Key divergence:** redress uses standalone policy objects; recourse uses policy keys with a `PolicyProvider` for centralized configuration. This is intentional — Python services tend toward explicit configuration, while Go services often benefit from centralized policy management.

---

## v1.1 — Unified Policy Model & Circuit Breakers

**Theme:** Complete the resilience story with a unified architecture

**Target:** Q1 2026

### Architectural Change: Unified Policy Model

The addition of circuit breakers motivates a broader architectural shift. Rather than bolting features onto `RetryPolicy`, v1.1 introduces a **unified `Policy` model** where retry is one optional component among several.

This aligns with the architecture proven in [recourse](https://github.com/aponysus/recourse) (the Go resilience library), where policies are containers for multiple resilience components.

**Key changes:**
- New `Policy` class as the unified resilience container
- New `Retry` class to hold retry-specific configuration
- `RetryPolicy` becomes sugar for `Policy(retry=Retry(...))`
- Full backward compatibility — existing code continues to work

**Proposed API:**
```python
from redress import Policy, Retry, CircuitBreaker
from redress import default_classifier
from redress.strategies import decorrelated_jitter

# === The unified model ===
policy = Policy(
    # Retry configuration (optional)
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        strategies={...},           # Per-class overrides
        max_attempts=5,
        max_unknown_attempts=2,
        deadline_s=60,
    ),
    
    # Circuit breaker (optional)
    circuit_breaker=CircuitBreaker(
        failure_threshold=5,
        window_s=60,
        recovery_timeout_s=30,
        trip_on={ErrorClass.TRANSIENT, ErrorClass.SERVER_ERROR},
    ),
    
    # Future: budget, hedge, etc.
)

result = policy.call(my_op, operation="fetch_user")


# === Backward-compatible sugar ===
# RetryPolicy remains as convenient shorthand
from redress import RetryPolicy

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
)
# Equivalent to: Policy(retry=Retry(...))


# === Async support ===
from redress import AsyncPolicy, AsyncRetry

async_policy = AsyncPolicy(
    retry=AsyncRetry(...),
    circuit_breaker=CircuitBreaker(...),  # Shared, thread-safe
)


# === Circuit breaker without retries ===
policy = Policy(
    circuit_breaker=CircuitBreaker(...),
)


# === @retry decorator ===
@retry  # Uses default Policy with default Retry
def fetch_user():
    ...

@retry(
    classifier=default_classifier,
    circuit_breaker=CircuitBreaker(...),
)
def fetch_user_with_breaker():
    ...
```

**Execution order within Policy:**
```
1. Circuit breaker check (fail fast if open)
2. Retry loop (if retry configured)
   a. Execute operation
   b. Classify result
   c. If retryable, sleep and retry
3. Circuit breaker record (success/failure of the overall operation after retries)
4. Future: fallback execution if configured
```

**Migration guide:**
```python
# v1.0 (still works in v1.1+)
from redress import RetryPolicy
policy = RetryPolicy(classifier=..., strategy=...)

# v1.1+ explicit unified model
from redress import Policy, Retry
policy = Policy(retry=Retry(classifier=..., strategy=...))

# Both produce equivalent behavior
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
        ErrorClass.RATE_LIMIT: 3,   # More sensitive to rate limits
    },
)

# Sharing across policies (common pattern)
user_policy = Policy(
    retry=Retry(strategy=decorrelated_jitter(max_s=1.0)),
    circuit_breaker=breaker,
)

order_policy = Policy(
    retry=Retry(strategy=decorrelated_jitter(max_s=5.0)),
    circuit_breaker=breaker,  # Same downstream, shared breaker
)
```

**State inspection:**
```python
breaker.state          # CircuitState.CLOSED | OPEN | HALF_OPEN
breaker.failure_count  # Current failure count in window
breaker.last_failure   # Timestamp of last failure
breaker.is_open        # Convenience bool
```

**Observability events to add:**
- `circuit_opened`
- `circuit_half_open`
- `circuit_closed`
- `circuit_rejected` (call rejected due to open circuit)

**Observability metrics to add:**
- `redress.retry.success_after_retries` (counter; label `retry.attempt`)

#### 2. Structlog Integration Example
**Priority:** Medium | **Effort:** Small

Add documentation and example showing clean structlog integration:

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

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
    on_log=structured_log_hook,
)
```

**Deliverables:**
- `docs/snippets/structlog_integration.py`
- Documentation section in Observability page

#### 3. OpenTelemetry Contrib Module
**Priority:** Medium | **Effort:** Medium

Separate package or contrib module: `redress-otel` or `redress.contrib.otel`

```python
from redress.contrib.otel import otel_hooks

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
    **otel_hooks(),  # Adds on_metric and on_log with OTEL integration
)
```

**Features:**
- Span creation for retry sequences
- Span events for individual attempts
- Metrics: `redress.retries`, `redress.retry.duration`, `redress.retry.success_after_retries`, `redress.circuit.state`
- Attributes: `error.class`, `retry.attempt`, `operation`

#### 4. Comparison Documentation
**Priority:** Medium | **Effort:** Small

New docs page: "Redress vs. Alternatives"

**Libraries to compare:**
- tenacity (most popular)
- backoff (decorator-focused)
- stamina (newer, similar philosophy)
- opnieuw (Channable's library)
- retrying (legacy, unmaintained)

**Comparison dimensions:**
- API philosophy
- Error classification support
- Async support
- Observability hooks
- Circuit breaker support
- Performance

---

## v1.2 — Classification Refinements

**Theme:** Handle edge cases cleanly

**Target:** Q2 2026

### Features

#### 1. Classification Context
**Priority:** High | **Effort:** Medium

Enable classifiers to pass additional context to strategies without increasing ErrorClass cardinality.

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Classification:
    error_class: ErrorClass
    context: dict[str, Any] = field(default_factory=dict)

# Classifier can return ErrorClass (backward compatible) or Classification
def http_classifier_v2(exc: BaseException) -> ErrorClass | Classification:
    if isinstance(exc, HTTPError):
        if exc.status == 429 and exc.headers.get("Retry-After"):
            return Classification(
                ErrorClass.RATE_LIMIT,
                {"retry_after": int(exc.headers["Retry-After"])}
            )
        # ... rest of classification
    return ErrorClass.UNKNOWN
```

**Strategy signature update:**
```python
# Old (still supported)
def strategy(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float

# New (optional)
def strategy(attempt: int, classification: Classification, prev_sleep: float | None) -> float
```

**Integration with unified Policy model:**
```python
policy = Policy(
    retry=Retry(
        classifier=http_classifier_v2,  # Returns Classification with context
        strategy=retry_after_aware_strategy,
    ),
)
```

#### 2. Retry-After Strategy
**Priority:** Medium | **Effort:** Small

Built-in strategy that respects Retry-After when provided via Classification context:

```python
from redress.strategies import retry_after_or

# Use Retry-After if present, otherwise fall back to decorrelated jitter
strategy = retry_after_or(decorrelated_jitter(max_s=60.0))
```

#### 3. Additional Built-in Classifiers
**Priority:** Medium | **Effort:** Medium

Expand classifier coverage for common libraries:

| Classifier | Library | Notes |
|------------|---------|-------|
| `aiohttp_classifier` | aiohttp | Client and server errors |
| `grpc_classifier` | grpcio | gRPC status codes |
| `boto3_classifier` | boto3/botocore | AWS error codes (throttling, service unavailable) |
| `redis_classifier` | redis-py | Connection errors, busy loading, etc. |

**Implementation approach:**
- Optional dependencies (extras)
- `pip install redress[boto3]` installs boto3 classifier
- Classifiers fail gracefully if library not installed

---

## v1.3 — Advanced Patterns

**Theme:** Production hardening

**Target:** Q3 2026

### Features

#### 1. Retry Budgets
**Priority:** High | **Effort:** Medium

Prevent retry storms during outages by limiting total retries across operations.

```python
from redress import Policy, Retry, Budget

# Shared budget across all operations using policies that reference it
budget = Budget(
    max_retries_per_window=100,  # Max retry attempts
    window_s=60,                  # Rolling window
)

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
    ),
    budget=budget,
)

# When budget exhausted, calls fail immediately without retry
# Observability event: budget_exhausted
```

**Design notes:**
- Thread-safe counter implementation
- Async-safe (no blocking)
- Budget can be shared across multiple policies
- Gradual recovery as window slides
- Aligns with recourse's budget model

#### 2. Testing Utilities
**Priority:** High | **Effort:** Medium

Make redress easy to test against:

```python
from redress.testing import (
    FakePolicy,
    RecordingPolicy,
    DeterministicStrategy,
    no_retries,
    instant_retries,
)

# Disable retries entirely in tests
with no_retries():
    result = function_using_redress()

# Record retry behavior for assertions
policy = RecordingPolicy(real_policy)
result = policy.call(flaky_fn)
assert policy.attempts == 3
assert policy.events == ["retry", "retry", "success"]
assert policy.classifications == [ErrorClass.TRANSIENT, ErrorClass.TRANSIENT]
assert policy.total_sleep_s == pytest.approx(1.5, rel=0.1)

# Deterministic sleeps for reproducible tests
policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=DeterministicStrategy([0.1, 0.2, 0.4]),  # Exact sleep times
    ),
)

# Instant retries (no sleeping, but still retry logic)
policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=instant_retries(),
    ),
)

# Test circuit breaker behavior
from redress.testing import FakeCircuitBreaker

breaker = FakeCircuitBreaker(initial_state=CircuitState.OPEN)
policy = Policy(circuit_breaker=breaker)
# Calls will fail fast with circuit_rejected
```

#### 3. Timeout-First Integration
**Priority:** Medium | **Effort:** Medium

Distinguish between deadline (wall-clock limit) and per-attempt timeout:

```python
policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        deadline_s=60,            # Total wall-clock time (existing)
        attempt_timeout_s=10,     # Per-attempt timeout (new)
    ),
)
```

**Behavior:**
- Each attempt is cancelled after `attempt_timeout_s`
- Timeout counts as TRANSIENT by default
- Deadline is still respected overall
- Aligns with recourse's `TimeoutPerAttempt` / `OverallTimeout` distinction

#### 4. Adaptive Strategies
**Priority:** Low | **Effort:** Large

Strategies that adjust based on recent success/failure rates:

```python
from redress.strategies import adaptive

strategy = adaptive(
    base=decorrelated_jitter(max_s=5.0),
    success_rate_threshold=0.5,  # Below this, increase backoff
    backoff_multiplier=2.0,      # How much to increase
    recovery_rate=0.1,           # How fast to return to base
)
```

**Note:** This is complex and may not be worth the added complexity. Consider based on user demand.

---

## v1.4+ — Ecosystem Expansion

**Theme:** Integrations & contrib modules

**Target:** Q4 2026+

### Focus Areas

#### Framework Integrations
Separate packages to avoid dependency bloat:

| Package | Framework | Integration Point |
|---------|-----------|-------------------|
| `redress-django` | Django | Middleware, DB retry |
| `redress-flask` | Flask | Extension, error handlers |
| `redress-celery` | Celery | Task decorator, autoretry replacement |
| `redress-fastapi` | FastAPI | Middleware (example exists, formalize) |

#### Additional Contrib Modules

| Module | Purpose |
|--------|---------|
| `redress.contrib.prometheus` | Prometheus metrics export |
| `redress.contrib.datadog` | Datadog APM integration |
| `redress.contrib.sentry` | Sentry breadcrumbs for retries |

#### Deferred / Contrib: Hedging (Async-first, Experimental)
Hedging is not in the core roadmap. Consider a contrib package later; async-first is more natural in Python, and sync hedging has GIL and load-amplification risks.

---

## Documentation Roadmap

### v1.1 Documentation
- [ ] **Unified Policy model guide** — Explain the architectural change
- [ ] **Migration guide: RetryPolicy → Policy** — Show equivalence, explain backward compat
- [ ] Comparison page: "Redress vs. Alternatives"
- [ ] Structlog integration example
- [ ] Circuit breaker concepts and usage
- [ ] OpenTelemetry setup guide
- [ ] Update all existing examples to show both styles

### v1.2 Documentation
- [ ] Classification Context guide
- [ ] Retry-After handling patterns
- [ ] Classifier authoring guide (expanded)

### v1.3 Documentation
- [ ] Retry budgets and backpressure
- [ ] Testing guide
- [ ] Production checklist (expanded)
- [ ] Recipes/Cookbook section:
  - Retrying with idempotency keys
  - Retry context propagation in async task queues
  - Per-tenant retry policies
  - Graceful degradation (retry → fallback → default)
  - Combining with caching

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

- `v1.1.0` — Circuit Breakers & Observability
- `v1.2.0` — Classification Refinements
- `v1.3.0` — Advanced Patterns
- `v1.4.0` — Ecosystem Expansion
- `backlog` — Good ideas, not yet scheduled

---

## Community & Feedback

### Pre-Implementation Feedback

Before implementing major features, share API designs for feedback:

1. Draft README section showing proposed usage
2. Post to:
   - Hacker News (Show HN)
   - Python Discord
   - Reddit r/Python
   - Twitter/X
3. Create GitHub Discussion for design feedback
4. Iterate on design before committing

### Adoption Tracking

Monitor adoption through:
- GitHub stars/forks
- PyPI download stats
- GitHub issues/discussions
- Community mentions

### Feature Requests

Track feature requests in GitHub Discussions (not Issues) until triaged and accepted into roadmap.

---

## Open Questions

### Circuit Breaker Design
- [x] ~~Composition vs. integration?~~ **Decided: Unified `Policy` model** (aligned with recourse)
- [ ] Should circuit breakers be per-ErrorClass or global? (Leaning: global with per-class thresholds)
- [ ] Should half-open state use a probe request or percentage of traffic?
- [ ] Should circuit state be exposed via the observability hook or separate callback?

### Classification Context
- [ ] Should context be mutable during retry sequence?
- [ ] Should strategies be able to write back to context?

### Retry Budgets
- [x] ~~Should budget be per-policy or shareable across policies?~~ **Decided: Shareable** (aligned with recourse)
- [ ] Should budget exhaustion raise a specific exception or return a result type?
- [ ] Missing budget behavior: fail-open or fail-closed? (recourse uses fail-closed by default)

### Naming
- [ ] `Policy` vs `ResiliencePolicy` for the unified class?
- [x] ~~`RetryConfig` vs `Retry` for the retry component?~~ **Decided: `Retry`**

---

## Changelog

| Date | Change |
|------|--------|
| 2024-12-24 | Initial roadmap created |
| 2024-12-24 | Decided: Unified `Policy` model for v1.1 (aligned with recourse architecture) |
| — | v1.0.0 released 🎉 |
