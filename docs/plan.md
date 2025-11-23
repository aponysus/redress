3. Tests + CI polish

Goal: show that you treat this like a production library: good coverage, type-checked, linted, CI’d.

3.1 Unit tests

Tasks

Ensure pytest is in your dev dependencies.

Create tests/ with files like:

test_error_classification.py

test_retry_policy_basic.py

test_retry_policy_deadlines.py

test_async_retry_policy.py

Concrete test scenarios to cover:

Classification

PermanentError / RateLimitError / etc. map to correct ErrorClass.

Exceptions with status / code attributes map correctly for 4xx / 5xx.

Name-based heuristics (e.g., TimeoutError, exception message containing “connection reset”) behave as expected.

Unknown error classification falls back to ErrorClass.UNKNOWN.

Sync retry behavior

Successful first call: on_metric gets a single success.

Transient failures that eventually succeed:

on_metric sees a sequence like retry, retry, success.

Number of attempts matches expectations.

Permanent error:

No retries; on_metric sees permanent_fail.

Original exception is re-raised.

Max attempts exceeded:

Check max_attempts branch.

Ensure it stops even if deadline not reached.

Deadline exceeded:

Use a fake time provider (if possible) or set super-low deadlines and stub time.monotonic in tests.

Async retry behavior

Mirror the above but with AsyncRetryPolicy using pytest.mark.asyncio.

Consider a small property-based test for backoff strategies if you want to flex:

Use hypothesis on attempt numbers and ensure:

Sleep times are non-negative.

Sleep times are bounded according to your strategy parameters.

Not mandatory, but looks very “senior”.

3.2 CI with GitHub Actions

Tasks

Add .github/workflows/ci.yml:

Jobs:

lint:

Run ruff and mypy.

test:

Run pytest.

Optional: coverage (e.g., pytest --cov=reflexio).

Python versions to test: at least 3.10, 3.11, 3.12.

Add badges to README:

Build status (![CI](https://github.com/<you>/reflexio/actions/workflows/ci.yml/badge.svg)).

Optional: coverage badge if you wire a service.

Ensure pyproject.toml or ruff.toml / mypy.ini exist with sane defaults so the configs don’t look half-baked.