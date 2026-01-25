from typing import Any

from ..circuit import CircuitState
from ..errors import ErrorClass, StopReason
from .types import FailureCause, LogHook, MetricHook, RetryOutcome


def _emit_breaker_event(
    *,
    event: str,
    state: CircuitState,
    klass: ErrorClass | None,
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
) -> None:
    tags: dict[str, Any] = {"state": state.value}
    if klass is not None:
        tags["class"] = klass.name
    if operation:
        tags["operation"] = operation

    if on_metric is not None:
        try:
            on_metric(event, 0, 0.0, tags)
        except Exception:
            pass

    if on_log is not None:
        fields = {"attempt": 0, "sleep_s": 0.0, **tags}
        try:
            on_log(event, fields)
        except Exception:
            pass


def _build_policy_outcome(
    *,
    ok: bool,
    value: Any | None,
    stop_reason: StopReason | None,
    attempts: int,
    last_class: ErrorClass | None,
    last_exception: BaseException | None,
    last_result: Any | None,
    cause: FailureCause | None,
    elapsed_s: float,
    next_sleep_s: float | None = None,
) -> RetryOutcome[Any]:
    return RetryOutcome(
        ok=ok,
        value=value if ok else None,
        stop_reason=stop_reason,
        attempts=attempts,
        last_class=last_class,
        last_exception=last_exception,
        last_result=last_result,
        cause=cause,
        elapsed_s=elapsed_s,
        next_sleep_s=next_sleep_s,
    )
