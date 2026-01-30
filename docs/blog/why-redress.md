# Why Failure Handling Should Be Policy (and Why Redress Exists)

Most systems don't *design* failure handling. They accumulate it:

- "wrap it in a retry decorator"
- "add exponential backoff"
- "some endpoints should fail fast"

Then you discover you're operating a distributed system with a pile of inconsistent, implicit rules.

**Redress is a failure-policy layer:** classify failures once, then apply consistent retries, caps, breaker decisions, and telemetry across a codebase. It's drop-in, sync/async-consistent, and bounded by default.

---

## 1. The core idea: classify, then respond

Before you decide "retry or not," you need to decide:

> **What kind of failure is this?**

Redress classifies failures into a small, fixed set of semantic error classes:

- `PERMANENT`
- `CONCURRENCY`
- `RATE_LIMIT`
- `SERVER_ERROR`
- `TRANSIENT`
- `UNKNOWN`

This set is intentionally coarse. The goal isn't perfect diagnosis. The goal is to separate failures that should behave differently:

- rate limits should back off slowly
- transient blips can retry quickly
- unknown failures should be tightly capped
- some failures should never be retried

Classification is the shared substrate for everything else.

---

## 2. A unified policy, not a pile of wrappers

Redress centers on a unified `Policy` container:

```python
from redress import CircuitBreaker, ErrorClass, Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        deadline_s=60.0,
        max_attempts=6,
        strategies={
            ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
            ErrorClass.TRANSIENT: decorrelated_jitter(max_s=1.0),
        },
    ),
    circuit_breaker=CircuitBreaker(
        failure_threshold=5,
        window_s=60.0,
        recovery_timeout_s=30.0,
        trip_on={ErrorClass.SERVER_ERROR, ErrorClass.CONCURRENCY},
    ),
)

result = policy.call(lambda: do_work(), operation="fetch_user")
```

This is the point: **one model** where the same classification coordinates multiple failure responses.

- retries are one response
- circuit breaking is another
- stop conditions are explicit and inspectable
- observability uses the same lifecycle everywhere

---

## 3. Why "retry libraries" tend to fail in production

Most retry libraries are fine at the call-site ergonomics: decorators, backoff math, "try N times."

The failure modes show up later:

### Treating all failures the same

Retrying rate limits like transient network errors turns a small event into a prolonged incident.

### Unbounded retry behavior

Retries need deterministic envelopes: deadlines, max attempts, and caps for unknown failures. Without bounds, outages get amplified.

### Separate systems for retries and breakers

If retries and circuit breakers don't share semantics and observability, they drift. You end up debugging "why did this fail fast?" as a separate universe from "why did this retry?"

### Lack of stop reasons

If you can't answer "why did we stop?" you can't operate the system effectively.

---

## 4. Backoff isn't one-size-fits-all

Once failures are classified, backoff becomes a policy decision instead of a single global knob.

Per-class strategies make intent explicit:

- rate limits back off aggressively
- transient blips retry quickly
- concurrency errors can use short jitter to avoid thundering herds

That's the practical win of "classify, then dispatch."

---

## 5. Bounded behavior is non-negotiable

Redress is designed around deterministic envelopes:

- `deadline_s` caps total time spent
- `max_attempts` caps total tries
- `max_unknown_attempts` prevents blind looping when classification is uncertain

These aren't "nice to have." They're what prevent retry storms and mystery behavior.

If you need to inspect *why* you stopped, use `execute()` and check the outcome:

```python
outcome = policy.execute(do_work)
print(outcome.stop_reason)  # ABORTED, DEADLINE_EXCEEDED, SCHEDULED, etc.
```

---

## 6. Observability is part of the contract

Retries and breakers hide behavior unless you surface it deliberately.

Redress exposes a small, consistent set of lifecycle hooks (`on_metric`, `on_log`, and attempt hooks) so observability isn't scattered:

```python
def metric_hook(event, attempt, sleep_s, tags):
    print(event, attempt, sleep_s, tags)

policy.call(my_op, on_metric=metric_hook, operation="sync_op")
```

The point isn't just that you *can* log. It's that the policy emits a coherent narrative:

- what was classified
- what response was chosen
- why it stopped

That's what makes failure handling operable.

---

## 7. Sync and async shouldn't be separate worlds

Failure handling is hard enough without a different mental model for asyncio.

Redress aims for sync/async symmetry: same policy shape, same semantics, async variants where needed.

---

## 8. What redress is (and is not)

Redress is for engineers who want failure handling to be:

- explicit
- bounded
- observable
- consistent across a codebase

It is not trying to be a workflow engine or a framework that owns your entire reliability stack.

It's a library of failure-policy primitives that compose cleanly inside real services.

---

## Where to go next

GitHub: https://github.com/aponysus/redress

Docs: https://aponysus.github.io/redress/

Getting started: https://aponysus.github.io/redress/getting-started/
