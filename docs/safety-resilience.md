# Safety and resilience

This page covers how redress behaves under failure and how to configure it for production.

## Hook failure isolation

`on_metric` and `on_log` are best-effort. Hook exceptions are swallowed inside the retry loop, so observability failures never change retry behavior. This keeps workloads safe, but it also means hook failures are silent unless you handle them.

Recommended handling:

- Keep hooks fast and side-effect light; avoid blocking I/O or retries inside the hook.
- If a hook calls a networked backend, set short timeouts and consider queueing/buffering.
- Wrap hooks and log failures so you can detect when observability breaks.

Example wrapper:

```python
def safe_metric_hook(hook, logger):
    def _hook(event, attempt, sleep_s, tags):
        try:
            hook(event, attempt, sleep_s, tags)
        except Exception as exc:
            logger.warning("redress_metric_hook_failed", error=str(exc))
    return _hook
```

If you need hook failures to affect control flow, enforce that outside of hooks; hooks are intentionally isolated.

## Backoff jitter and thundering herds

When many workers fail at once, fixed or purely exponential delays can line up retries and create a thundering herd. Jitter spreads attempts over time so upstreams can recover.

Guidance:

- Prefer jittered strategies like `decorrelated_jitter` for defaults.
- Use larger `base_s` and `max_s` for `RATE_LIMIT` to widen the retry window.
- Keep `max_s` high enough to spread bursts; too-small caps still synchronize retries.
- Use per-class strategies and caps (`per_class_max_attempts`, `max_attempts`) to limit coordinated retries.
- For high fan-out callers, add concurrency limits (queues, semaphores) in addition to jitter.

See [Retry strategies](concepts/strategies.md) for details on built-ins.

## Production checklist

- Timeouts: set per-attempt timeouts shorter than `deadline_s` so there is room for retries.
- Deadline: tune `deadline_s` to your upstream SLA; it bounds wall-clock retry time.
- Max attempts: set `max_attempts` and `max_unknown_attempts` to prevent runaway loops.
- Per-class caps: use `per_class_max_attempts` for noisy classes like `RATE_LIMIT`/`SERVER_ERROR`.
- Backoff: use jittered strategies with `max_s` sized to the recovery window.
- Observability: set `operation`, attach `on_metric` or `on_log`, keep tags low-cardinality.
- Key metrics: watch `retry`, `success`, `deadline_exceeded`, `max_attempts_exceeded`,
  `max_unknown_attempts_exceeded`, `permanent_fail`, and distributions of `sleep_s`.

See [Observability](observability.md) for hook patterns and alerting ideas.
