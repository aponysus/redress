# Codebase and documentation review — 2026-09-24

Review baseline: commit `46f047a` (release preparation for 1.4.1).
The maintainer subsequently confirmed that PyPI still has 1.4.0.
This document records the findings at that baseline; it does not imply that
all findings are fixed by the release-integrity follow-up.

## Assessment against the vision

Redress has a coherent model: classify failures into a small semantic taxonomy,
then apply explicit policy decisions for retries, budgets, circuit breakers,
and terminal outcomes. `Policy` / `AsyncPolicy`, the compatibility wrappers,
structured outcomes, and optional integrations support that model well.

The main gap is consistency when components interact. The design promises
bounded execution, best-effort observability, consistent sync/async semantics,
and circuit breakers that observe final operation outcomes. Cancellation,
lifecycle hooks, strategy composition, and backend-specific constraints expose
cases where those promises do not hold. Expand the behavioral contract and
integration tests before expanding the feature surface.

The new migration, performance, and troubleshooting guides are useful adoption
improvements. Older documentation still contradicts some of their precise
behavioral descriptions.

## Scope and evidence

Inspected the retry runners, shared decision logic, circuit breaker, strategies,
configuration, HTTP/framework/provider integrations, observability adapters,
release and CI workflows, tests, and documentation. Ran focused local
reproductions in addition to the existing suite.

Baseline validation:

- 424 tests passed, with 86.13% coverage (85% required).
- Ruff and mypy passed; mypy checked 58 source files.
- Strict MkDocs build passed.
- FastAPI/Starlette, Celery, and Prometheus were not installed in the review
  environment. Findings involving those dependencies distinguish source review
  or strict test doubles from real-backend reproduction.
- No production load test or remote GitHub Actions execution was performed.

Severity: **High** means release integrity, possible duplicate/corrupted work,
or blocked recovery. **Medium** means materially incorrect behavior or a
contract mismatch. Integration risks that lack a transport-level reproduction
are explicitly marked as such.

## R1 — Release tag and package metadata disagree

**High. Confirmed from local tagged source.**

Both the baseline checkout and local `v1.4.1` tag declare `version = "1.4.0"`
in [pyproject.toml](https://github.com/aponysus/redress/blob/46f047a/pyproject.toml). The project entry in
[uv.lock](https://github.com/aponysus/redress/blob/46f047a/uv.lock) is also 1.4.0, while the changelog has a 1.4.1 entry.
The original [release workflow](https://github.com/aponysus/redress/blob/46f047a/.github/workflows/release.yml) builds
from that metadata, creates a GitHub release before publishing, and enables
`skip-existing`. This can advertise a new release while skipping an already
published package version. The maintainer verified PyPI remains at 1.4.0.

**Resolution:** compare tag, package version, lockfile, latest dated changelog
entry, and embedded wheel/sdist metadata. Reject mismatches before upload.
Fail on existing artifacts instead of silently skipping them. Publish to PyPI
before creating the GitHub release. Add the source/artifact checks to PR CI.

**Follow-up in this change:** package and lockfile metadata are aligned to
1.4.1; gates and regression tests are added. Existing tags and remote releases
are not modified. Publication and resolution of the old tag remain maintainer
release steps; see [Contributing](https://github.com/aponysus/redress/blob/main/CONTRIBUTING.md#release-process).

## R2 — Attempt-end hook failures can repeat successful work

**High. Reproduced. Open.**

In [sync_core.py](https://github.com/aponysus/redress/blob/46f047a/src/redress/policy/runner/sync_core.py), `execute()`
invokes the successful attempt-end hook inside the exception boundary used to
classify operation failures. The async runner has the same structure.

Reproduction: an operation returns successfully, but the first
`on_attempt_end` call raises `TimeoutError`. With subsequent hook calls
succeeding, `execute()` invokes the operation twice and reports two attempts.
`call()` instead propagates that hook exception after one operation.

This can duplicate side effects and violates execution-mode consistency.

**Resolution:** separate operation errors from lifecycle callback errors.
Specify which hooks are best-effort and which intentionally propagate.
Never interpret an observation failure as a retryable operation failure.
Test both modes, both runners, start/end hooks, and successful mutations.

## R3 — Cancellation can strand a half-open circuit breaker

**High. Reproduced. Open.**

[AsyncPolicy._execute_with_retry](https://github.com/aponysus/redress/blob/46f047a/src/redress/policy/async_policy.py)
awaits `retry.execute()` without cancellation cleanup around it. The runner
propagates `CancelledError`, bypassing breaker completion/cancellation.

Reproduction: open the breaker, advance its clock to admit a half-open probe,
then cancel the probe operation through `execute()`. Further calls remain
rejected even after advancing the clock far beyond recovery time because the
probe remains in flight.

**Resolution:** ensure every admitted execution releases or completes its
admission on every exit. Include cancellation during operations, sleep, and
callbacks; also test exceptional exits from classifiers/strategies and sync
system-exiting exceptions through `execute()`.

## R4 — Breaker completions lack admission ownership

**High. Reproduced with deterministic admission/completion sequences. Open.**

[CircuitBreaker](https://github.com/aponysus/redress/blob/46f047a/src/redress/circuit.py) locks mutations but associates
neither a generation nor an admission token with completions.

Two failing sequences:

1. Two calls enter while closed. One failure opens the breaker. After recovery,
   a new half-open probe starts. The older call then succeeds and closes the
   breaker before that new probe finishes.
2. A half-open probe is active. A separate `Policy` without a retry component
   aborts before breaker admission. `check_abort_no_retry()` calls
   `record_cancel()`, releasing the other call's probe and allowing another.

**Resolution:** track ownership and generation of admissions internally.
A call that never acquired admission must not release one. Ignore stale
completions when deciding the current probe's outcome. Add tests for concurrent
in-flight calls crossing open/half-open transitions.

## R5 — Retried request bodies may differ from the original

**High. Reproduced with real HTTPX and MockTransport. Open.**

[HTTPX request wrappers](https://github.com/aponysus/redress/blob/46f047a/src/redress/contrib/httpx.py) pass the same
request arguments on every retry. A PUT using `content=iter([b"payload"])`
sent `b"payload"` on the first attempt and `b""` on its retry after a 503.
The second attempt returned 200, silently accepting a different request body.

Method idempotency does not establish that a body can be replayed. Related
requests/aiohttp wrappers need the same review; this specific reproduction was
HTTPX only.

**Resolution:** define replayability explicitly. Support immutable buffered
bodies or a request/body factory; reject or require opt-in for unsupported
streams. Test generators, file offsets, multipart content, and async streams.

## R6 — Prometheus labels do not match the documented schema

**Medium. Confirmed by source review and strict-label simulation. Open.**

[prometheus_hooks](https://github.com/aponysus/redress/blob/46f047a/src/redress/contrib/prometheus.py) forwards all tags
as labels. The [documented example](../snippets/prometheus_contrib.py) declares
`event`, `class`, and `operation`. Failure events add `err`, `cause`, and
sometimes `stop_reason`; success events can omit `class`.

The real client's [label validation](https://raw.githubusercontent.com/prometheus/client_python/master/prometheus_client/metrics.py)
requires the supplied names to match its declared schema. A strict test double
implementing that check recorded zero events for failure and success examples.
Redress swallows the label exceptions, hiding the telemetry loss. Existing
adapter tests use a permissive fake, so they pass.

**Resolution:** define a fixed schema or an explicit label projection with
values for missing labels. Apply it to counters and histograms. Test a real
Prometheus registry and the documented snippet, checking exported samples.

## R7 — Budget exhaustion does not terminate OpenTelemetry state

**Medium. Reproduced with the repository's tracer/meter doubles. Open.**

[otel.py](https://github.com/aponysus/redress/blob/46f047a/src/redress/contrib/otel.py) omits `BUDGET_EXHAUSTED` from its
terminal-event set. A budget-exhausted call left its span open; a subsequent
successful operation used the same span, mixing two operations.

**Resolution:** account for every terminal outcome and cancellation. Test
consecutive operations, nesting, and task contexts. Avoid manually maintained
terminal-event lists drifting from the execution model.

Related concern: the older [otel_metric_hook](https://github.com/aponysus/redress/blob/46f047a/src/redress/metrics.py)
uses floating-point `sleep_s` as a metric attribute. Jitter can create many
attribute combinations, contrary to the low-cardinality invariant. Represent
delay as a measured value, not a series dimension.

## R8 — Per-class limit documentation contradicts behavior

**Medium. Reproduced. Open.**

[Usage](../usage.md#per-class-strategies-and-limits) says a class limit of 1
allows one total attempt and no retries. The counter stops only when class
failures exceed the limit. With a generous global ceiling, limits 0, 1, and 2
produced 1, 2, and 3 failing calls respectively.

The [troubleshooting guide](../troubleshooting.md) describes the actual
behavior, leaving two conflicting contracts in the docs.

**Resolution:** reconcile documentation with shipped behavior and add a shared
counting table for global, unknown, and per-class limits. Do not silently
change established semantics as a documentation fix; evaluate compatibility
before changing the implementation.

## R9 — Deadline admission and configuration validation are inconsistent

**Medium. Reproduced. Open.**

[Design notes](../design_notes.md) promise deadline checks before every attempt.
The runners do not consistently enforce a check immediately before operation
invocation. Advancing a fake clock past a one-second deadline inside an
attempt-start hook still allowed the operation to run and return success.
This is distinct from the inability to interrupt an already-running sync call,
which the new performance guide correctly documents.

Constructors also accept `max_attempts=0`, negative deadlines, and negative
unknown caps that [doctor](https://github.com/aponysus/redress/blob/46f047a/src/redress/cli.py) rejects. A negative
deadline still allowed an immediately successful operation.

**Resolution:** define the deadline admission boundary and check it uniformly.
Share validation between configuration construction and CLI diagnostics;
include finite-number checks. Test initial admission, hooks consuming time,
post-sleep boundaries, and interactions with per-attempt timeouts.

## R10 — Adaptive strategy feedback is incomplete and lost by composition

**Medium. Reproduced. Open.**

[Retry state](https://github.com/aponysus/redress/blob/46f047a/src/redress/policy/state.py) records success only on a
strategy selected earlier in that same execution. Immediate successes do not
balance past failures. One failure followed by ten immediate successful
operations left an adaptive strategy's multiplier at its maximum.

The documented `retry_after_or(adaptive(...))` composition returns a function
that does not expose the adaptive feedback methods. In this configuration the
adaptive strategy received no feedback at all.

**Resolution:** define a composable feedback interface and clarify whether it
measures attempts or final operations. Test observed behavior through policies,
including immediate successes, different classes, and wrapped strategies.

## R11 — Terminal exceptions are classified twice

**Medium. Reproduced. Open.**

[Policy.call](https://github.com/aponysus/redress/blob/46f047a/src/redress/policy/policy.py) classifies a terminal
exception again for breaker accounting, even when no breaker is configured.
One failing attempt invoked a custom classifier twice. A stateful classifier
that returned TRANSIENT then PERMANENT left the breaker closed with `call()`
but opened it with `execute()`.

**Resolution:** preserve and reuse the original classification. Avoid duplicate
classifier calls and ensure exception preservation if classification fails.
Verify wrappers, `call()`/`execute()`, and sync/async behavior together.

## Additional gaps and risks

- **Deferred state ownership:** [Celery integration](https://github.com/aponysus/redress/blob/46f047a/src/redress/contrib/celery.py)
  starts a fresh policy execution per delivery. A fake task repeatedly deferred
  five deliveries with `max_attempts=2`; each execution reset attempt/time/backoff
  state. Celery has its own [retry limits](https://docs.celeryq.dev/en/stable/userguide/tasks.html#retrying),
  so this does not prove real Celery retries forever. Document scheduler-owned
  limits and provide a recipe preserving a logical operation's total budget.
- **Response cleanup:** the aiohttp wrapper does not explicitly release discarded
  retryable responses. Unread bodies can hold connections according to the
  [aiohttp response contract](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientResponse.release).
  Pool exhaustion remains an integration risk requiring a transport-level
  reproduction; it was not demonstrated against a live aiohttp server.
- **Operation naming:** HTTP client wrappers use concrete paths. Removing query
  strings does not remove resource IDs. FastAPI builds operation names before
  `call_next`, so route-template availability needs a real framework test.
  Framework tests currently rely on dummy requests with prepopulated routes.
- **No-retry outcome accounting:** an operation raising `AbortRetry` through
  `Policy().execute()` reports zero attempts even though it ran once, because
  the same outcome builder serves both preflight and in-operation aborts.
- **Framework retry boundaries:** request-body replay and response lifecycle
  behavior need real Starlette/FastAPI tests, not only protocol fakes. Prefer
  retrying the failing downstream operation when whole-handler replay is unsafe.
- **Roadmap drift:** public roadmap says “Delivered through v1.2”; internal
  checklists still show several shipped features/docs as incomplete. Reconcile
  with the changelog and distinguish delivered, maintenance, and proposed work.
- **Narrow performance evidence:** current microbenchmarks measure batches of
  simple synchronous calls. Add comparisons for async, capture/hooks, timeout
  threads, contention, budgets, and breakers; report per-operation units and
  environment details. No production performance claim was validated here.

## Recommended sequence and completion criteria

1. **Release integrity:** source/tag/artifact checks in CI and publishing;
   matching 1.4.1 metadata; resolve the existing tag deliberately; verify the
   package actually published before declaring the release complete.
2. **Execution correctness:** resolve R2–R5 with regression tests covering
   duplicate side effects, cancellation, admission ownership, and upload replay.
3. **Observability and contracts:** fix R6–R11; make docs examples executable
   against real backend schemas and reconcile documented limits/deadlines.
4. **Integration hardening:** add a matrix of sync/async, call/execute,
   exception/result, cancellation, hooks, budgets, and breaker transitions.
   Add real-client tests for resources and framework lifecycles. Coverage alone
   is insufficient: all reproduced failures coexisted with a passing suite.
5. **Expansion:** clarify externally scheduled execution ownership and publish
   a durable queue/database recipe before implementing a broader resumable
   execution API. Defer additional framework wrappers and experimental hedging
   until the existing contracts are dependable.
