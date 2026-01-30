# Redress

> redress (v.): to remedy or to set right.

redress is a failure-policy library for Python services.

It treats retries, circuit breakers, and stop conditions as coordinated responses to classified failure, rather than independent wrappers. The goal is to make failure behavior explicit, bounded, and observable across a codebase.

## Why redress?

- **Per-class backoff:** Tune retries by coarse error class (429 vs. 5xx vs. deadlocks).
- **Pluggable classifiers:** Built-ins for HTTP status and SQLSTATE; easy to supply your own.
- **Sync/async symmetry:** Same semantics for threads and asyncio, plus a zero-arg `@retry` decorator.
- **Deterministic envelopes:** Deadlines, max attempts, and caps for unknown errors.
- **Best-effort observability:** Metric/log hooks that never break workloads.

[More background here](blog/why-redress.md)

## Quick start

```python
from redress import retry

@retry  # default_classifier + decorrelated_jitter(max_s=5.0)
def fetch_user():
    ...
```

Async is the same:

```python
@retry
async def fetch_user_async():
    ...
```

Prefer policies directly?

```python
from redress import Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        deadline_s=30,
        max_attempts=5,
    )
)

result = policy.call(lambda: do_work(), operation="sync_task")
```

## What’s inside

- **API highlights:** `Policy` / `Retry`, `CircuitBreaker`, `RetryPolicy` / `AsyncRetryPolicy`, `@retry`, classifiers (`default`, `http_classifier`, `sqlstate_classifier`, `pyodbc_classifier`), strategies (`decorrelated_jitter`, `equal_jitter`, `token_backoff`), hooks (`on_metric`, `on_log`), context manager reuse.
- **Use cases:** HTTP 429/5xx, DB deadlocks/SQLSTATE 40001, queue/worker retries, third-party API calls, async services.
- **Production pointers:** Set `deadline_s` and `max_attempts`, cap `max_unknown_attempts`, keep tags low-cardinality (`class`, `operation`, `err`), attach metrics/log hooks.

## Where to go next

- [Getting started](getting-started.md) – install and first examples.
- [Concepts](concepts/error-classes.md) – error classes, strategies, policies, decorators.
- [Observability](observability.md) – metrics/log hooks and patterns.
- [Safety and resilience](safety-resilience.md): hook isolation, jitter guidance, production checklist.
- [Usage](usage.md) - basic usage patterns.
- [Reference flows](reference-flows.md) - end-to-end service patterns.
- [Examples & Integrations](examples/index.md) – runnable snippets for HTTP, DB, workers, FastAPI, benchmarks.
- [API reference](api.md) – entry points at a glance.
