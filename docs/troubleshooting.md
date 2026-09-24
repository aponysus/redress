# Troubleshooting

Start with the terminal outcome: did the operation fail, how many times did it
run, which class was selected, and why did retries stop? Reproduce with a local
operation before changing production limits.

## Capture a diagnostic outcome

This standalone example intentionally produces an unknown failure:

```python
from redress import Policy, Retry, StopReason, default_classifier
from redress.testing import instant_retries

def broken_operation():
    raise RuntimeError("example failure")

policy = Policy(retry=Retry(
    classifier=default_classifier,
    strategy=instant_retries,  # Diagnostic example only; use jitter in production.
    max_attempts=5,
    max_unknown_attempts=2,
    deadline_s=5.0,
))
outcome = policy.execute(
    broken_operation, operation="diagnostic", capture_timeline=True,
)
assert not outcome.ok
assert outcome.attempts == 3
assert outcome.stop_reason is StopReason.MAX_UNKNOWN_ATTEMPTS
assert outcome.timeline is not None
for event in outcome.timeline.events:
    print(event.attempt, event.event, event.stop_reason)
```

`execute()` returns a `RetryOutcome` for ordinary operation failures.
Inspect `ok`, `attempts`, `last_class`, `stop_reason`, and `cause`; use
`last_exception` or `last_result` when needed. Successful outcomes have no stop
reason. Cancellation, `KeyboardInterrupt`, and `SystemExit` still propagate.
Do not log entire results, exception messages, or request payloads by default.

For async operations use `AsyncPolicy(retry=AsyncRetry(...))` and
`await policy.execute(...)`. Timeline capture is opt-in on `execute()`.

## Match the symptom to the cause

| Symptom or stop reason | What to check | Remedy |
| --- | --- | --- |
| `NON_RETRYABLE_CLASS` | Classifier returned `AUTH`, `PERMISSION`, or `PERMANENT` | Fix credentials/input or correct the classifier; a strategy cannot make those classes retryable |
| `MAX_UNKNOWN_ATTEMPTS` | Unrecognized exceptions or results | Add an explicit classification; the default cap of 2 stops on the third unknown failure |
| `MAX_ATTEMPTS_GLOBAL` | Total calls reached `max_attempts` | Count the initial call; inspect whether more attempts could actually recover |
| `MAX_ATTEMPTS_PER_CLASS` | Failures exceeded the configured class allowance | Check the class-specific counter; a limit of 0 allows the initial operation but no retry for that class |
| `NO_STRATEGY` | Neither a matching per-class strategy nor a fallback exists | Configure `strategy` or cover the intended class in `strategies` |
| `DEADLINE_EXCEEDED` | Attempts, hooks, or waits used the retry time budget | Inspect timing and client timeouts before increasing the deadline |
| `BUDGET_EXHAUSTED` | Other calls consumed the shared rolling-window allowance | Inspect sharing scope and downstream load; avoid recreating the budget per call |
| `ABORTED` | `abort_if`, an `AbortRetry` exception, or an aborting sleeper | Check shutdown/drain state and sleeper decisions |
| `SCHEDULED` | A sleeper returned `SleepDecision.DEFER` | Arrange execution externally using `next_sleep_s`; Redress has not queued a job |
| Zero attempts and `CircuitOpenError` | Circuit breaker rejected admission | Inspect downstream health and breaker recovery settings |

Class allowances count failures of that class within one execution and stop
when the count exceeds the allowance. For example, `per_class_max_attempts={
ErrorClass.TRANSIENT: 1}` permits a retry after the first transient failure and
stops at the second, unless another limit stops execution first.

A breaker rejection from `execute()` is stored in `last_exception`, with zero
attempts and `stop_reason=None`; do not look for a circuit-open `StopReason`.
`call()` raises `CircuitOpenError`. See [Circuit breakers](concepts/circuit-breakers.md).

## Results appear successful even when the service failed

By default only exceptions trigger classification. An HTTP client returning a
503 response without raising needs a suitable `result_classifier`, or an
operation that raises on that response. A result classifier must return `None`
for success and `ErrorClass` or `Classification` for failure, not `True`/`False`.
See [HTTP recipes](recipes/http.md).

If a failed result exhausts retries, `call()` raises `RetryExhaustedError`.
Use `execute()` to inspect `last_result` and make a fallback decision. Ordinary
terminal operation exceptions from `call()` are re-raised directly.

## Calls exceed the deadline or keep running after timeout

The retry deadline does not interrupt an in-flight operation. Sync attempt
timeouts cannot stop an already-running thread; async cancellation may need
cleanup time. Configure native client timeouts and inspect blocking work.
See [Performance tuning](performance-tuning.md) for the timing model.

## Hooks are silent or slow

`on_metric(event, attempt, sleep_s, tags)` and `on_log(event, fields)` have
different signatures. Their exceptions are swallowed to isolate observability
failures. Test adapters directly and add local error reporting around export
code. They still run inline, so slow hooks add latency and can block async work.
See [Observability](observability.md).

## Retry-After or attempt counts look unexpected

Use a classifier that supplies `Classification.retry_after_s` together with
`retry_after_or(...)`. A plain error class does not carry the header value.
Selected delays are limited by remaining retry time. Also inspect nested SDK,
client, queue, or decorator retries when downstream request counts exceed the
policy's attempt count.

The final allowed failed attempt reports exhaustion without emitting `retry`,
consuming a retry token, or sleeping. Earlier retry decisions may still be
aborted or deferred, so a `retry` event does not guarantee another operation
invocation. Use `outcome.attempts` or attempt hooks to count calls.

## Prepare a useful bug report

Include Redress and Python versions, sync/async mode, a minimal policy and
operation, expected versus actual behavior, and sanitized outcome/timeline
fields. Replace external services with local failures and use
[testing utilities](testing.md) for repeatable timing. Exclude credentials,
request bodies, and identifying tags.
