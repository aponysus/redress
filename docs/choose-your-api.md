# Choose your API

Use this page when you want the fastest path to the right redress entry point.

## Recommended default

Start with `Policy(retry=Retry(...))` unless you have a clear reason not to.

It is the canonical API and the best long-term fit when you need explicit
configuration, circuit breakers, budgets, shared hooks, or structured outcomes.

## Decision table

| If you want... | Use this |
| --- | --- |
| The smallest decorator-based entry point | `@retry` |
| Retry-only behavior with an explicit object | `RetryPolicy` / `AsyncRetryPolicy` |
| The full model and canonical API | `Policy(retry=Retry(...))` / `AsyncPolicy(retry=AsyncRetry(...))` |
| Structured stop reasons and outcomes instead of relying on exceptions alone | `execute()` |
| Shared operation/hook settings across repeated calls | `.context(...)` |
| Async execution | `AsyncPolicy`, `AsyncRetryPolicy`, or `@retry` on an async function |

## `@retry`

Use `@retry` when you want the least setup and the function itself is the unit
of policy.

```python
from redress import retry

@retry
def fetch_user():
    ...
```

Move up from the decorator when you need circuit breakers, shared budgets,
multiple operations sharing one policy, or explicit structured outcomes.

## `RetryPolicy`

Use `RetryPolicy` when you want retry-only behavior with an explicit object but
do not need the wider policy container yet.

```python
from redress import RetryPolicy, default_classifier
from redress.strategies import decorrelated_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=3.0),
)
```

This is convenient sugar for retry-only flows. When the execution model grows
to include circuit breaking, budgets, or richer composition, move to `Policy`.

## `Policy(retry=Retry(...))`

Use `Policy` when you want the canonical core model.

```python
from redress import Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        max_attempts=5,
        deadline_s=30.0,
    ),
)
```

This is the preferred starting point for new integrations.

## `execute()`

Use `execute()` when you want a structured `RetryOutcome` with stop reason,
attempt count, and last failure information.

```python
outcome = policy.execute(do_work, operation="sync_task")
if outcome.ok:
    print(outcome.value)
else:
    print(outcome.stop_reason)
```

Choose `execute()` over `call()` when the caller needs to branch on retry
termination semantics instead of just handling exceptions.

## `.context(...)`

Use `.context(...)` when repeated calls share the same operation name, hooks, or
execution settings.

```python
with policy.context(operation="batch_sync") as retry:
    retry(task1)
    retry(task2)
```

This keeps repeated calls consistent and removes repeated keyword arguments.

## Async equivalents

Async follows the same decision logic:

- `@retry` on an async function for minimal setup
- `AsyncRetryPolicy` for retry-only sugar
- `AsyncPolicy(retry=AsyncRetry(...))` as the canonical async API
- `await policy.execute(...)` when you need `RetryOutcome`

## Practical rule

- If you are unsure, start with `Policy` / `AsyncPolicy`.
- If the codebase is tiny and retry-only, `RetryPolicy` is acceptable.
- If you need the smallest wrapper, use `@retry`.
- If the caller needs structured terminal state, use `execute()`.
