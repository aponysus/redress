# Performance tuning

Tune for useful recovery within your latency and load limits. Measure a healthy
operation and representative failure cases before changing policy settings.

## Allocate time to attempts and waits

Estimate total latency as operation time across attempts, plus backoff sleeps,
plus classifier and hook work. `max_attempts` includes the initial call.
Start with a small attempt ceiling and an explicit `deadline_s` derived from
the caller's time budget, leaving room for response handling.

`deadline_s` uses monotonic elapsed time to bound retry decisions and sleeps.
It is not a hard wall-clock timeout: a running operation can outlive it and can
return successfully after it. Use client connect/read/request timeouts to bound
actual I/O. `attempt_timeout_s` is optional and is not automatically reduced to
the remaining retry deadline.

- Sync attempt timeouts run the operation in a thread. A timeout stops waiting,
  but cannot terminate a running thread. Later retries can overlap unfinished
  work, and thread-affine clients may be unsuitable. Prefer native client timeouts.
- Async attempt timeouts use `asyncio.wait_for`. Cancellation cleanup can extend
  elapsed time; blocking code or suppressed cancellation prevents prompt timeout.

Do not retry mutations unless they have an idempotency or deduplication plan.

## Start with a bounded policy

The following values are illustrative, not workload-independent defaults:

```python
from redress import Budget, ErrorClass, Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

# Construct once per downstream sharing domain, not once per request.
budget = Budget(max_retries=20, window_s=10.0)
policy = Policy(retry=Retry(
    classifier=default_classifier,
    strategy=decorrelated_jitter(base_s=0.1, max_s=1.0),
    strategies={
        ErrorClass.RATE_LIMIT: decorrelated_jitter(base_s=0.5, max_s=2.0),
    },
    max_attempts=3,
    max_unknown_attempts=1,
    deadline_s=5.0,
    budget=budget,
))

assert policy.call(lambda: "ok", operation="catalog_read") == "ok"
```

Reuse client connections and policy objects. Share a budget between operations
that should compete for the same retry allowance; separate unrelated downstreams.
Budgets are in-process objects, so multiple processes or replicas have separate
allowances. They limit retry decisions, not initial traffic or concurrency.
The current engine may also consume a token for the terminal failed attempt
before reporting global exhaustion; do not treat token usage as an exact count
of additional downstream requests.

## Tune load as well as latency

| Observation | Adjustment to evaluate |
| --- | --- |
| Retries rarely recover before the caller gives up | Reduce attempts or change the recovery window; inspect client timeouts |
| Many workers retry together | Add jitter and widen its range; avoid tiny caps |
| Rate limits dominate | Honor Retry-After, reduce admission rate, and tune a separate rate-limit strategy |
| Retry traffic grows during an outage | Share a budget, bound concurrency, and consider a circuit breaker |
| Unknown failures dominate | Improve classification before raising the unknown cap |
| Event loop stalls | Remove blocking operations and blocking hooks from async execution |

Nested retry layers multiply work: two layers allowing three attempts each can
issue nine downstream calls. Choose which layer owns retries, including SDK
and queue retry settings. Use a queue or semaphore to limit concurrent work;
a retry budget does not provide that limit. See [Safety and resilience](safety-resilience.md).

## Keep the execution path inexpensive

Keep classifiers local and deterministic. Avoid network requests inside
classifiers, strategies, or hooks. Metric and log hooks run inline even though
their exceptions are isolated; buffer export work when appropriate and keep
`operation` names and tags low-cardinality.

Enable `execute(..., capture_timeline=True)` for selected diagnostic calls.
Capturing a timeline allocates records; compare measurements with capture and
hooks both enabled and disabled. Avoid retaining outcomes indefinitely because
they can retain exception and result objects.

## Measure changes reproducibly

From a repository checkout:

```bash
python -m pip install -e '.[dev]'
python docs/snippets/bench_retry.py
```

The [benchmark snippet](examples/index.md#benchmarks-pyperf) measures successful calls
and one-retry calls without real backoff sleeps. Each reported benchmark
invocation includes 1,000 policy calls and policy setup; it is not a direct
per-call latency figure. It does not measure network latency, production
contention, timeout threads, or a telemetry backend.

Record Python version, hardware, concurrency, policy settings, and hook/capture
settings with results. Compare the same environment before and after a change.
For service load tests measure throughput, p50/p95/p99 latency, downstream calls
per operation, recovery rate, and stop reasons under both healthy and failing
conditions. Change one setting at a time and retain the change only if it helps
the application's latency and load targets. Use [Troubleshooting](troubleshooting.md)
when measurements show unexpected retry behavior.
