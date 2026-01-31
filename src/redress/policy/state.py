import collections
import math
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from ..classify import Classification
from ..errors import AbortRetryError, ErrorClass, StopReason
from ..events import EventName
from ..strategies import BackoffContext
from .base import _BaseRetryPolicy, _normalize_classification
from .types import AbortPredicate, FailureCause, LogHook, MetricHook


@dataclass(frozen=True)
class _RetryDecision:
    action: Literal["retry", "raise"]
    sleep_s: float = 0.0
    context: BackoffContext | None = None


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
        abort_if: AbortPredicate | None,
    ) -> None:
        self.policy = policy
        self.on_metric = on_metric
        self.on_log = on_log
        self.operation = operation
        self.abort_if = abort_if
        self.start_mono = time.monotonic()
        self.prev_sleep: float | None = None
        self.last_exc: BaseException | None = None
        self.last_result: Any | None = None
        self.last_class: ErrorClass | None = None
        self.last_classification: Classification | None = None
        self.last_cause: FailureCause | None = None
        self.last_stop_reason: StopReason | None = None
        self.unknown_attempts: int = 0
        self.per_class_counts: dict[ErrorClass, int] = collections.defaultdict(int)
        self._last_strategy: Any | None = None

    def check_abort(self, attempt: int) -> None:
        if self.abort_if is None:
            return
        if not self.abort_if():
            return

        self.last_stop_reason = StopReason.ABORTED
        self.emit(
            EventName.ABORTED.value,
            attempt,
            0.0,
            stop_reason=StopReason.ABORTED,
        )
        raise AbortRetryError()

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
        cause: FailureCause | None = None,
        classification: Classification | None = None,
    ) -> None:
        tags: dict[str, Any] = {}

        if klass is not None:
            tags["class"] = klass.name

        if exc is not None:
            tags["err"] = type(exc).__name__

        if stop_reason is not None:
            tags["stop_reason"] = stop_reason.value

        if cause is not None:
            tags["cause"] = cause

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
                event == EventName.RETRY.value
                and classification is not None
                and classification.retry_after_s is not None
            ):
                fields["retry_after_s"] = classification.retry_after_s
            try:
                self.on_log(event, fields)
            except Exception:
                pass

    def record_failure(
        self,
        *,
        classification: Classification,
        cause: FailureCause,
        exc: BaseException | None,
        result: Any | None,
    ) -> None:
        self.last_class = classification.klass
        self.last_classification = classification
        self.last_cause = cause
        if cause == "exception":
            self.last_exc = exc
            self.last_result = None
        else:
            self.last_result = result
            self.last_exc = None

    def record_success(self) -> None:
        strategy = self._last_strategy
        if strategy is None:
            return
        record = getattr(strategy, "record_success", None)
        if callable(record):
            record()

    def handle_exception(self, exc: BaseException, attempt: int) -> _RetryDecision:
        """
        Process an exception and return a retry/raise decision.
        """
        classification = _normalize_classification(self.policy.classifier(exc))
        return self._handle_failure(
            classification=classification,
            attempt=attempt,
            cause="exception",
            exc=exc,
            result=None,
        )

    def handle_result(
        self,
        result: Any,
        classification: Classification,
        attempt: int,
    ) -> _RetryDecision:
        """
        Process a result-based failure and return a retry/raise decision.
        """
        return self._handle_failure(
            classification=classification,
            attempt=attempt,
            cause="result",
            exc=None,
            result=result,
        )

    def _handle_failure(
        self,
        *,
        classification: Classification,
        attempt: int,
        cause: FailureCause,
        exc: BaseException | None,
        result: Any | None,
    ) -> _RetryDecision:
        self.record_failure(
            classification=classification,
            cause=cause,
            exc=exc,
            result=result,
        )
        klass = classification.klass
        self.per_class_counts[klass] += 1

        limit = self.policy.per_class_max_attempts.get(klass)
        if limit is not None and self.per_class_counts[klass] > limit:
            self.last_stop_reason = StopReason.MAX_ATTEMPTS_PER_CLASS
            self.emit(
                EventName.MAX_ATTEMPTS_EXCEEDED.value,
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.MAX_ATTEMPTS_PER_CLASS,
                cause=cause,
            )
            return _RetryDecision("raise")

        if klass in (ErrorClass.PERMANENT, ErrorClass.AUTH, ErrorClass.PERMISSION):
            self.last_stop_reason = StopReason.NON_RETRYABLE_CLASS
            self.emit(
                EventName.PERMANENT_FAIL.value,
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.NON_RETRYABLE_CLASS,
                cause=cause,
            )
            return _RetryDecision("raise")

        if klass is ErrorClass.UNKNOWN:
            self.unknown_attempts += 1
            if (
                self.policy.max_unknown_attempts is not None
                and self.unknown_attempts > self.policy.max_unknown_attempts
            ):
                self.last_stop_reason = StopReason.MAX_UNKNOWN_ATTEMPTS
                self.emit(
                    EventName.MAX_UNKNOWN_ATTEMPTS_EXCEEDED.value,
                    attempt,
                    0.0,
                    klass,
                    exc,
                    stop_reason=StopReason.MAX_UNKNOWN_ATTEMPTS,
                    cause=cause,
                )
                return _RetryDecision("raise")

        if self.elapsed() > self.policy.deadline:
            self.last_stop_reason = StopReason.DEADLINE_EXCEEDED
            self.emit(
                EventName.DEADLINE_EXCEEDED.value,
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.DEADLINE_EXCEEDED,
                cause=cause,
            )
            return _RetryDecision("raise")

        strategy = self.policy._select_strategy(klass)
        if strategy is None:
            self.last_stop_reason = StopReason.NO_STRATEGY
            self.emit(
                EventName.NO_STRATEGY_CONFIGURED.value,
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.NO_STRATEGY,
                cause=cause,
            )
            return _RetryDecision("raise")

        self._last_strategy = strategy
        record_failure = getattr(strategy, "record_failure", None)
        if callable(record_failure):
            record_failure(klass)

        remaining = self.policy.deadline - self.elapsed()
        remaining_s = remaining.total_seconds()
        if remaining_s <= 0:
            self.last_stop_reason = StopReason.DEADLINE_EXCEEDED
            self.emit(
                EventName.DEADLINE_EXCEEDED.value,
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.DEADLINE_EXCEEDED,
                cause=cause,
            )
            return _RetryDecision("raise")

        ctx = _build_backoff_context(
            attempt=attempt,
            classification=classification,
            prev_sleep_s=self.prev_sleep,
            remaining_s=remaining_s,
            cause=cause,
        )
        sleep_s = strategy(ctx)

        if not math.isfinite(sleep_s):
            sleep_s = 0.0

        sleep_s = max(0.0, sleep_s)
        sleep_s = min(sleep_s, remaining_s)

        if self.policy.budget is not None and not self.policy.budget.consume():
            self.last_stop_reason = StopReason.BUDGET_EXHAUSTED
            self.emit(
                EventName.BUDGET_EXHAUSTED.value,
                attempt,
                0.0,
                klass,
                exc,
                stop_reason=StopReason.BUDGET_EXHAUSTED,
                cause=cause,
            )
            return _RetryDecision("raise")

        self.prev_sleep = sleep_s
        self.emit(
            EventName.RETRY.value,
            attempt,
            sleep_s,
            klass,
            exc,
            cause=cause,
            classification=classification,
        )
        return _RetryDecision("retry", sleep_s, ctx)
