import asyncio
import collections
import functools
import inspect
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, ParamSpec, TypeVar, cast, overload

from .classify import Classification, default_classifier
from .config import RetryConfig
from .errors import ErrorClass, StopReason
from .strategies import (
    BackoffContext,
    BackoffFn,
    ContextStrategyFn,
    LegacyStrategyFn,
    StrategyFn,
    decorrelated_jitter,
)

ClassifierFn = Callable[[BaseException], ErrorClass | Classification]
MetricHook = Callable[[str, int, float, dict[str, Any]], None]
LogHook = Callable[[str, dict[str, Any]], None]
P = ParamSpec("P")
T = TypeVar("T")


class _BaseRetryPolicy:
    def __init__(
        self,
        *,
        classifier: ClassifierFn,
        strategy: StrategyFn | None = None,
        strategies: Mapping[ErrorClass, StrategyFn] | None = None,
        deadline_s: float = 60.0,
        max_attempts: int = 6,
        max_unknown_attempts: int | None = 2,
        per_class_max_attempts: Mapping[ErrorClass, int] | None = None,
    ) -> None:
        if strategies is None and strategy is None:
            raise ValueError(
                "RetryPolicy requires either a default 'strategy' or a "
                "'strategies' mapping (or both)."
            )

        self.classifier: ClassifierFn = classifier
        self._strategies: dict[ErrorClass, BackoffFn] = {
            klass: _normalize_strategy(fn) for klass, fn in (strategies or {}).items()
        }
        self._default_strategy: BackoffFn | None = (
            _normalize_strategy(strategy) if strategy is not None else None
        )
        self.deadline: timedelta = timedelta(seconds=deadline_s)
        self.max_attempts: int = max_attempts
        self.max_unknown_attempts: int | None = max_unknown_attempts
        self.per_class_max_attempts: dict[ErrorClass, int] = dict(per_class_max_attempts or {})

    def _select_strategy(self, klass: ErrorClass) -> BackoffFn | None:
        return self._strategies.get(klass, self._default_strategy)


@dataclass(frozen=True)
class _RetryDecision:
    action: Literal["retry", "raise"]
    sleep_s: float = 0.0


def _normalize_classification(result: ErrorClass | Classification) -> Classification:
    if isinstance(result, Classification):
        return result
    return Classification(klass=result)


def _build_backoff_context(
    *,
    attempt: int,
    classification: Classification,
    prev_sleep_s: float | None,
    remaining_s: float | None,
    cause: Literal["exception", "result"],
) -> BackoffContext:
    # Centralized so result-based retries can switch cause to "result" later.
    return BackoffContext(
        attempt=attempt,
        classification=classification,
        prev_sleep_s=prev_sleep_s,
        remaining_s=remaining_s,
        cause=cause,
    )


def _normalize_strategy(strategy: StrategyFn) -> BackoffFn:
    try:
        signature = inspect.signature(strategy)
    except (TypeError, ValueError) as exc:
        raise TypeError("Strategy must accept (ctx) or (attempt, klass, prev_sleep_s)") from exc

    required_positional = [
        p
        for p in signature.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.default is inspect.Parameter.empty
    ]
    required_kwonly = [
        p
        for p in signature.parameters.values()
        if p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty
    ]

    if required_kwonly:
        raise TypeError("Strategy must accept (ctx) or (attempt, klass, prev_sleep_s)")

    if len(required_positional) == 1:
        return cast(ContextStrategyFn, strategy)

    if len(required_positional) == 3:
        legacy = cast(LegacyStrategyFn, strategy)

        def wrapped(ctx: BackoffContext) -> float:
            return legacy(ctx.attempt, ctx.klass, ctx.prev_sleep_s)

        return wrapped

    raise TypeError("Strategy must accept (ctx) or (attempt, klass, prev_sleep_s)")


class _RetryState:
    """
    Shared state and utilities for sync/async retry execution.
    """

    def __init__(
        self,
        *,
        policy: _BaseRetryPolicy,
        on_metric: MetricHook | None,
        on_log: LogHook | None,
        operation: str | None,
    ) -> None:
        self.policy = policy
        self.on_metric = on_metric
        self.on_log = on_log
        self.operation = operation
        self.start_mono = time.monotonic()
        self.prev_sleep: float | None = None
        self.last_exc: BaseException | None = None
        self.last_class: ErrorClass | None = None
        self.unknown_attempts: int = 0
        self.per_class_counts: dict[ErrorClass, int] = collections.defaultdict(int)

    def elapsed(self) -> timedelta:
        return timedelta(seconds=time.monotonic() - self.start_mono)

    def emit(
        self,
        event: str,
        attempt: int,
        sleep_s: float,
        klass: ErrorClass | None = None,
        exc: BaseException | None = None,
        stop_reason: StopReason | None = None,
        classification: Classification | None = None,
    ) -> None:
        tags: dict[str, Any] = {}

        if klass is not None:
            tags["class"] = klass.name

        if exc is not None:
            tags["err"] = type(exc).__name__

        if stop_reason is not None:
            tags["stop_reason"] = stop_reason.value

        if self.operation:
            tags["operation"] = self.operation

        if self.on_metric is not None:
            try:
                self.on_metric(event, attempt, sleep_s, tags)
            except Exception:
                pass

        if self.on_log is not None:
            fields = {"attempt": attempt, "sleep_s": sleep_s, **tags}
            if (
                event == "retry"
                and classification is not None
                and classification.retry_after_s is not None
            ):
                fields["retry_after_s"] = classification.retry_after_s
            try:
                self.on_log(event, fields)
            except Exception:
                pass

    def handle_exception(self, exc: BaseException, attempt: int) -> _RetryDecision:
        """
        Process an exception and return a retry/raise decision.
        """
        self.last_exc = exc
        classification = _normalize_classification(self.policy.classifier(exc))
        klass = classification.klass
        self.last_class = klass
        self.per_class_counts[klass] += 1

        limit = self.policy.per_class_max_attempts.get(klass)
        if limit is not None and self.per_class_counts[klass] > limit:
            self.emit(
                "max_attempts_exceeded",
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.MAX_ATTEMPTS_PER_CLASS,
            )
            return _RetryDecision("raise")

        if klass in (ErrorClass.PERMANENT, ErrorClass.AUTH, ErrorClass.PERMISSION):
            self.emit(
                "permanent_fail",
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.NON_RETRYABLE_CLASS,
            )
            return _RetryDecision("raise")

        if klass is ErrorClass.UNKNOWN:
            self.unknown_attempts += 1
            if (
                self.policy.max_unknown_attempts is not None
                and self.unknown_attempts > self.policy.max_unknown_attempts
            ):
                self.emit(
                    "max_unknown_attempts_exceeded",
                    attempt,
                    0.0,
                    klass,
                    exc,
                    stop_reason=StopReason.MAX_UNKNOWN_ATTEMPTS,
                )
                return _RetryDecision("raise")

        if self.elapsed() > self.policy.deadline:
            self.emit(
                "deadline_exceeded",
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.DEADLINE_EXCEEDED,
            )
            return _RetryDecision("raise")

        strategy = self.policy._select_strategy(klass)
        if strategy is None:
            self.emit(
                "no_strategy_configured",
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.NO_STRATEGY,
            )
            return _RetryDecision("raise")

        remaining = self.policy.deadline - self.elapsed()
        remaining_s = remaining.total_seconds()
        if remaining_s <= 0:
            self.emit(
                "deadline_exceeded",
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.DEADLINE_EXCEEDED,
            )
            return _RetryDecision("raise")

        ctx = _build_backoff_context(
            attempt=attempt,
            classification=classification,
            prev_sleep_s=self.prev_sleep,
            remaining_s=remaining_s,
            cause="exception",
        )
        sleep_s = strategy(ctx)

        if not math.isfinite(sleep_s):
            sleep_s = 0.0

        sleep_s = max(0.0, sleep_s)
        sleep_s = min(sleep_s, remaining_s)
        self.prev_sleep = sleep_s
        self.emit("retry", attempt, sleep_s, klass, exc, classification=classification)
        return _RetryDecision("retry", sleep_s)


@dataclass
class _RetryContext:
    policy: "RetryPolicy"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None

    def __enter__(self) -> Callable[..., T]:
        return self.call

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        result = self.policy.call(
            lambda: func(*args, **kwargs),
            on_metric=self.on_metric,
            on_log=self.on_log,
            operation=self.operation,
        )
        return cast(T, result)


@dataclass
class _AsyncRetryContext:
    policy: "AsyncRetryPolicy"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None

    async def __aenter__(self) -> Callable[..., Awaitable[T]]:
        return self.call

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    async def call(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        result = await self.policy.call(
            lambda: func(*args, **kwargs),
            on_metric=self.on_metric,
            on_log=self.on_log,
            operation=self.operation,
        )
        return result


class RetryPolicy(_BaseRetryPolicy):
    """
    Generic, pluggable retry loop with classification + backoff strategies.

    The policy itself is deliberately dumb:
      * It does not know about HTTP, SQL, Kafka, etc.
      * It only understands ErrorClass values and which strategy to use for each.
      * All domain logic lives in your classifier and strategy functions.

    Parameters
    ----------
    classifier:
        Function mapping an exception to an ErrorClass or a Classification.

    strategy:
        Optional default backoff strategy to use for *all* error classes
        that are not explicitly configured in `strategies`. This keeps the
        old "single strategy" usage working:

            RetryPolicy(
                classifier=default_classifier,
                strategy=decorrelated_jitter(),
                ...
            )

    strategies:
        Optional mapping from ErrorClass -> StrategyFn. Strategies may use the
        legacy `(attempt, klass, prev_sleep_s)` signature or the context-aware
        `(ctx: BackoffContext)` signature. If provided, per-class strategies
        override `strategy` for those specific classes.

        Example:

            strategies = {
                ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=1.0),
                ErrorClass.RATE_LIMIT:  decorrelated_jitter(max_s=60.0),
                ErrorClass.SERVER_ERROR: equal_jitter(),
            }

    deadline_s:
        Total wall-clock time (in seconds) allowed across all attempts.

    max_attempts:
        Hard cap on how many attempts will be made, regardless of deadline.

    max_unknown_attempts:
        Optional special cap for ErrorClass.UNKNOWN. If exceeded, the last
        exception is re-raised with its original traceback even if the
        global max_attempts is not yet hit.

    Notes
    -----
    * PERMANENT errors are never retried.
    * UNKNOWN errors default to being retried like TRANSIENT, but with an
      optional dedicated cap via max_unknown_attempts.
    """

    def __init__(
        self,
        *,
        classifier: ClassifierFn,
        strategy: StrategyFn | None = None,
        strategies: Mapping[ErrorClass, StrategyFn] | None = None,
        deadline_s: float = 60.0,
        max_attempts: int = 6,
        max_unknown_attempts: int | None = 2,
        per_class_max_attempts: Mapping[ErrorClass, int] | None = None,
    ) -> None:
        super().__init__(
            classifier=classifier,
            strategy=strategy,
            strategies=strategies,
            deadline_s=deadline_s,
            max_attempts=max_attempts,
            max_unknown_attempts=max_unknown_attempts,
            per_class_max_attempts=per_class_max_attempts,
        )

    @classmethod
    def from_config(
        cls,
        config: RetryConfig,
        *,
        classifier: ClassifierFn,
    ) -> "RetryPolicy":
        """
        Construct a RetryPolicy from a RetryConfig bundle.
        """
        return cls(
            classifier=classifier,
            strategy=config.default_strategy,
            strategies=config.class_strategies,
            deadline_s=config.deadline_s,
            max_attempts=config.max_attempts,
            max_unknown_attempts=config.max_unknown_attempts,
            per_class_max_attempts=config.per_class_max_attempts,
        )

    def call(
        self,
        func: Callable[[], Any],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> Any:
        """
        Execute `func` with retries according to this policy.

        Parameters
        ----------
        func:
            Zero-argument callable to invoke. All exceptions are intercepted
            and handled according to `classifier` and the configured backoff
            strategies.

        on_metric:
            Optional callback for observability. Signature:

                on_metric(
                    event: str,          # event name, see below
                    attempt: int,        # 1-based attempt number being executed
                    sleep_s: float,      # scheduled delay for retries, else 0.0
                    tags: Dict[str, Any],# safe tags (no payloads/messages)
                )

            Events emitted:
              * "success"              – func() returned successfully
              * "permanent_fail"       – PERMANENT/AUTH/PERMISSION classes, no retry
              * "deadline_exceeded"    – wall-clock deadline exceeded
              * "retry"                – a retry is scheduled
              * "no_strategy_configured" – missing strategy for a retryable class
              * "max_attempts_exceeded"– we hit max_attempts and re-raise with
                the original traceback
              * "max_unknown_attempts_exceeded" – UNKNOWN cap hit

            Default tags:
              * class – ErrorClass.name when available
              * err   – exception class name when an exception exists
              * stop_reason – terminal reason (only on terminal events)
              * operation – optional logical operation name from `operation`

            Hook errors are swallowed (best-effort) so user workloads are never
            interrupted by observability failures.

        on_log:
            Optional logging hook, invoked at the same points as on_metric.
            Signature:

                on_log(event: str, fields: Dict[str, Any]) -> None

            The fields dict includes attempt, sleep_s, and the same tags as
            on_metric. Errors are swallowed for the same reason as on_metric.

        operation:
            Optional logical name for the action being retried (e.g.,
            "fetch_user_profile"). Propagated into tags for metrics/logging.

        Returns
        -------
        Any
            The return value of func() if it eventually succeeds.

        Raises
        ------
        BaseException
            The original exception from the last attempt, re-raised with
            its original traceback after retries are exhausted or a
            non-retriable condition is hit.
        """
        state = _RetryState(
            policy=self,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
        )

        for attempt in range(1, self.max_attempts + 1):
            try:
                result = func()
                state.emit("success", attempt, 0.0)
                return result

            except asyncio.CancelledError:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                decision = state.handle_exception(exc, attempt)
                if decision.action == "raise":
                    raise

                time.sleep(decision.sleep_s)

                if state.elapsed() > self.deadline:
                    state.emit(
                        "deadline_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        state.last_exc,
                        stop_reason=StopReason.DEADLINE_EXCEEDED,
                    )
                    raise

                if attempt == self.max_attempts:
                    state.emit(
                        "max_attempts_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        state.last_exc,
                        stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                    )
                    raise

        # Defensive fallback if we exit the loop without returning or raising.
        state.emit(
            "max_attempts_exceeded",
            self.max_attempts,
            0.0,
            state.last_class,
            state.last_exc,
            stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
        )
        if state.last_exc is not None and state.last_exc.__traceback__ is not None:
            raise state.last_exc.with_traceback(state.last_exc.__traceback__)

        # Extremely unlikely: no exception and no result.
        raise RuntimeError("Retry attempts exhausted with no captured exception")

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> _RetryContext:
        """
        Context manager that binds hooks/operation for multiple calls.

        Usage:
            with policy.context(on_metric=hook, operation="batch") as retry:
                retry(fn1)
                retry(fn2, arg1, arg2)
        """
        return _RetryContext(self, on_metric, on_log, operation)


class AsyncRetryPolicy(_BaseRetryPolicy):
    """
    Async retry loop mirroring RetryPolicy semantics for awaitables.
    """

    @classmethod
    def from_config(
        cls,
        config: RetryConfig,
        *,
        classifier: ClassifierFn,
    ) -> "AsyncRetryPolicy":
        """
        Construct an AsyncRetryPolicy from a RetryConfig bundle.
        """
        return cls(
            classifier=classifier,
            strategy=config.default_strategy,
            strategies=config.class_strategies,
            deadline_s=config.deadline_s,
            max_attempts=config.max_attempts,
            max_unknown_attempts=config.max_unknown_attempts,
            per_class_max_attempts=config.per_class_max_attempts,
        )

    async def call(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> T:
        """
        Execute an async function with retries according to this policy.
        """
        state = _RetryState(
            policy=self,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
        )

        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await func()
                state.emit("success", attempt, 0.0)
                return result
            except asyncio.CancelledError:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                decision = state.handle_exception(exc, attempt)
                if decision.action == "raise":
                    raise

                await asyncio.sleep(decision.sleep_s)

                if state.elapsed() > self.deadline:
                    state.emit(
                        "deadline_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        state.last_exc,
                        stop_reason=StopReason.DEADLINE_EXCEEDED,
                    )
                    raise

                if attempt == self.max_attempts:
                    state.emit(
                        "max_attempts_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        state.last_exc,
                        stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                    )
                    raise

        state.emit(
            "max_attempts_exceeded",
            self.max_attempts,
            0.0,
            state.last_class,
            state.last_exc,
            stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
        )

        if state.last_exc is not None and state.last_exc.__traceback__ is not None:
            raise state.last_exc.with_traceback(state.last_exc.__traceback__)

        raise RuntimeError("Retry attempts exhausted with no captured exception")

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> _AsyncRetryContext:
        """
        Async context manager that binds hooks/operation for multiple calls.

        Usage:
            async with policy.context(on_metric=hook, operation="batch") as retry:
                await retry(async_fn1)
                await retry(async_fn2, arg)
        """
        return _AsyncRetryContext(self, on_metric, on_log, operation)


@overload
def retry(
    func: None = None,
    *,
    classifier: ClassifierFn = ...,
    strategy: StrategyFn | None = ...,
    strategies: Mapping[ErrorClass, StrategyFn] | None = ...,
    deadline_s: float = ...,
    max_attempts: int = ...,
    max_unknown_attempts: int | None = ...,
    per_class_max_attempts: Mapping[ErrorClass, int] | None = ...,
    on_metric: MetricHook | None = ...,
    on_log: LogHook | None = ...,
    operation: str | None = ...,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


@overload
def retry(
    func: Callable[P, T],
    *,
    classifier: ClassifierFn = ...,
    strategy: StrategyFn | None = ...,
    strategies: Mapping[ErrorClass, StrategyFn] | None = ...,
    deadline_s: float = ...,
    max_attempts: int = ...,
    max_unknown_attempts: int | None = ...,
    per_class_max_attempts: Mapping[ErrorClass, int] | None = ...,
    on_metric: MetricHook | None = ...,
    on_log: LogHook | None = ...,
    operation: str | None = ...,
) -> Callable[P, T]: ...


def retry(
    func: Callable[P, T] | None = None,
    *,
    classifier: ClassifierFn = default_classifier,
    strategy: StrategyFn | None = None,
    strategies: Mapping[ErrorClass, StrategyFn] | None = None,
    deadline_s: float = 60.0,
    max_attempts: int = 6,
    max_unknown_attempts: int | None = 2,
    per_class_max_attempts: Mapping[ErrorClass, int] | None = None,
    on_metric: MetricHook | None = None,
    on_log: LogHook | None = None,
    operation: str | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]] | Callable[P, T]:
    """
    Decorator that wraps a function in a RetryPolicy (sync) or AsyncRetryPolicy (async).

    Usage
    -----
        @retry(classifier=default_classifier, strategy=decorrelated_jitter())
        def fetch_user() -> str:
            ...

    Parameters mirror RetryPolicy/AsyncRetryPolicy. Hooks/operation can be set up-front.

    If neither `strategy` nor `strategies` is provided, a default
    decorrelated_jitter(max_s=5.0) strategy is injected.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        op_name = operation or getattr(func, "__name__", None)
        effective_strategy: StrategyFn | None
        if strategy is None and strategies is None:
            effective_strategy = decorrelated_jitter(max_s=5.0)
        else:
            effective_strategy = strategy

        if asyncio.iscoroutinefunction(func):
            async_policy = AsyncRetryPolicy(
                classifier=classifier,
                strategy=effective_strategy,
                strategies=strategies,
                deadline_s=deadline_s,
                max_attempts=max_attempts,
                max_unknown_attempts=max_unknown_attempts,
                per_class_max_attempts=per_class_max_attempts,
            )

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                result = await async_policy.call(
                    lambda: func(*args, **kwargs),
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=op_name,
                )
                return cast(T, result)

            return async_wrapper  # type: ignore[return-value]

        policy = RetryPolicy(
            classifier=classifier,
            strategy=effective_strategy,
            strategies=strategies,
            deadline_s=deadline_s,
            max_attempts=max_attempts,
            max_unknown_attempts=max_unknown_attempts,
            per_class_max_attempts=per_class_max_attempts,
        )

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            result = policy.call(
                lambda: func(*args, **kwargs),
                on_metric=on_metric,
                on_log=on_log,
                operation=op_name,
            )
            return cast(T, result)

        return wrapper

    if func is not None:
        return decorator(func)

    return decorator


# ---- Examples -----------------------------------------------------------------


def _example_usage() -> None:
    """
    Minimal usage example.

    This is not executed automatically; it's here as inline docs.
    """

    from .classify import default_classifier
    from .strategies import decorrelated_jitter, equal_jitter, token_backoff

    # Strategy registry tuned per error class
    strategies: dict[ErrorClass, StrategyFn] = {
        ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=1.0),
        ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
        ErrorClass.SERVER_ERROR: equal_jitter(max_s=30.0),
        ErrorClass.TRANSIENT: token_backoff(max_s=20.0),
        # UNKNOWN will fall back to the default strategy below
    }

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=10.0),  # default for UNKNOWN, etc.
        strategies=strategies,
        deadline_s=120.0,
        max_attempts=8,
        max_unknown_attempts=2,
    )

    def flaky_call() -> str:
        # Replace with your real logic
        return "ok"

    def metric_hook(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        print(f"[metric] event={event} attempt={attempt} sleep={sleep_s} tags={tags}")

    def log_hook(event: str, fields: dict[str, Any]) -> None:
        print(f"[log] event={event} fields={fields}")

    result = policy.call(
        flaky_call,
        on_metric=metric_hook,
        on_log=log_hook,
        operation="example_operation",
    )
    print("Result:", result)
