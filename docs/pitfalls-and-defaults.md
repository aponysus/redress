# Pitfalls and defaults

Use this page when you want the blunt version: the common failure-handling
footguns, the defaults that matter most, and the situations where redress
should be used more carefully.

## Start with these defaults

- Prefer `Policy(retry=Retry(...))` as the default API.
- Always set a real `deadline_s`.
- Keep `max_attempts` modest.
- Cap `UNKNOWN` failures with `max_unknown_attempts`.
- Use low-cardinality `operation` names and tags.
- Prefer stable classifiers over string heuristics.
- Use `execute()` when the caller needs stop-reason-aware control flow.

## When not to retry

Do not retry just because an exception happened.

Usually non-retryable:

- validation failures
- auth and permission failures
- known permanent input errors
- side-effecting operations with no idempotency plan
- business-rule failures that will not change with time

If the failure is not expected to improve with delay, retries add load without
adding value.

## Why `UNKNOWN` should be capped

`UNKNOWN` means the classifier could not confidently map the failure. That is a
signal to be conservative, not optimistic.

Use `max_unknown_attempts` to avoid broad “retry anything weird” behavior:

```python
retry=Retry(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
    max_unknown_attempts=2,
)
```

If you find yourself hitting the `UNKNOWN` cap often, improve the classifier
instead of widening the cap.

## Deadlines matter more than high attempt counts

Large `max_attempts` values without an overall deadline often create long,
unpredictable failure tails.

Prefer:

- a realistic `deadline_s`
- moderate `max_attempts`
- per-class backoff tuned to the dependency

Bad instinct:

- “set attempts to 20 just to be safe”

Better instinct:

- “set a 10s or 30s deadline and make retries fit inside that envelope”

## Keep observability tags low-cardinality

Good tags:

- `class`
- `operation`
- `stop_reason`
- `cause`
- `state`

Bad tags:

- full URLs
- user IDs
- request IDs
- trace IDs
- raw SQL
- exception messages

High-cardinality tags make metrics expensive and much less useful.

## When to use `execute()` instead of `call()`

Use `call()` when exception-style control flow is enough.

Use `execute()` when you need:

- `RetryOutcome.stop_reason`
- `RetryOutcome.attempts`
- `RetryOutcome.last_class`
- result-based terminal failures without exceptions
- deferred retry handling via `next_sleep_s`

If the caller is deciding what to do next based on why retries stopped, use
`execute()`.

## When the decorator is too small

`@retry` is fine for small wrappers. It becomes too small when you need:

- circuit breakers
- shared budgets
- multiple operations sharing one policy
- explicit `execute()` calls
- richer integration with frameworks, workers, or clients

At that point, move to explicit policy objects.

## Side effects and idempotency

Be careful retrying operations that mutate external state.

Examples:

- charge a card
- send an email
- publish a message
- write to a downstream system with no idempotency key

If you retry side-effecting operations, you need an idempotency or deduplication
plan outside the retry loop.

## Common anti-patterns

### Retrying validation failures

Do not retry errors that are caused by bad input or bad local state.

### Retrying broad unknown exceptions with no cap

This creates noisy, expensive failure behavior without confidence that retrying
is correct.

### Huge deadlines and huge attempts “just in case”

This makes failures slower and harder to reason about.

### Treating tags like logs

Hooks are not a place to stuff request payloads or arbitrary identifiers.

## Practical checklist

Before shipping a policy, ask:

1. What failures are actually retryable?
2. What is the maximum acceptable end-to-end latency?
3. Is `UNKNOWN` bounded?
4. Are metrics tags low-cardinality?
5. Is the operation safe to retry?
6. Should the caller use `call()` or `execute()`?
