# Migration

Use this page when you are evaluating the cost of moving from retry-only
libraries to redress.

## What changes when you move to redress

The main difference is abstraction level.

Most retry libraries focus on:

- retry predicates
- decorator ergonomics
- backoff behavior

redress adds:

- explicit semantic classification (`ErrorClass`)
- a canonical policy container
- structured stop reasons and outcomes
- shared retry budgets
- circuit breakers
- low-cardinality observability hooks

That means migration usually makes a few things more explicit, but gives you a
stronger model once the code stops being “just a decorator.”

## From Tenacity-style decorators

Typical pattern:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(5), wait=wait_exponential())
def fetch_user():
    ...
```

Nearest redress equivalent:

```python
from redress import retry, default_classifier
from redress.strategies import decorrelated_jitter

@retry(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
    max_attempts=5,
)
def fetch_user():
    ...
```

What becomes more explicit:

- how failures are classified
- what kinds of errors should be treated differently

What you gain:

- per-class behavior
- stable stop reasons
- a clean path to `Policy(...)`, budgets, and breakers

## From Backoff-style decorators

Typical pattern:

```python
import backoff

@backoff.on_exception(backoff.expo, Exception, max_tries=5)
def fetch_user():
    ...
```

Nearest redress equivalent:

```python
from redress import retry, default_classifier
from redress.strategies import decorrelated_jitter

@retry(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
    max_attempts=5,
)
def fetch_user():
    ...
```

What changes:

- retryability is classification-driven instead of “retry this broad exception set”
- you can move naturally toward explicit policy objects as behavior grows

## When to stop using decorator-only migration

Move from the decorator to `Policy` when you need:

- circuit breakers
- shared retry budgets
- result-based retries
- `execute()` / `RetryOutcome`
- multiple operations sharing one configuration

## Retry-only object migration

If you currently think in terms of a retry object rather than a decorator, the
closest shape is:

```python
from redress import RetryPolicy, default_classifier
from redress.strategies import decorrelated_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
    max_attempts=5,
    deadline_s=30.0,
)
```

Then, when you need the wider execution model:

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

## HTTP 429 / Retry-After migration

This is a common place where redress gets more valuable than a generic retry
decorator.

```python
from redress import RetryPolicy
from redress.extras import http_retry_after_classifier
from redress.strategies import decorrelated_jitter, retry_after_or

policy = RetryPolicy(
    classifier=http_retry_after_classifier,
    strategy=retry_after_or(decorrelated_jitter(max_s=10.0)),
    max_attempts=5,
)
```

This keeps rate limiting separate from generic transient failure handling.

## What redress makes more explicit on purpose

- failures should map to coarse semantic classes
- retries should be bounded
- observability should use stable, low-cardinality fields
- callers should be able to ask why retries stopped

If that explicitness feels heavy, the decorator may be enough. If the code is
already carrying ad-hoc retry rules, redress usually makes the behavior easier
to reason about.
