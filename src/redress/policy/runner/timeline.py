import time
from typing import Any, cast

from ...errors import ErrorClass, StopReason
from ..types import FailureCause, MetricHook, RetryTimeline, TimelineEvent


class _TimelineCollector:
    def __init__(self, timeline: RetryTimeline) -> None:
        self.timeline = timeline
        self.start = time.monotonic()

    def record(self, event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        elapsed_s = time.monotonic() - self.start
        error_class: ErrorClass | None = None
        stop_reason: StopReason | None = None
        cause: FailureCause | None = None

        klass = tags.get("class")
        if isinstance(klass, str):
            try:
                error_class = ErrorClass[klass]
            except KeyError:
                error_class = None

        reason = tags.get("stop_reason")
        if isinstance(reason, str):
            try:
                stop_reason = StopReason(reason)
            except ValueError:
                stop_reason = None

        raw_cause = tags.get("cause")
        if raw_cause in ("exception", "result"):
            cause = cast(FailureCause, raw_cause)

        self.timeline.add(
            TimelineEvent(
                attempt=attempt,
                event=event,
                elapsed_s=elapsed_s,
                sleep_s=sleep_s,
                error_class=error_class,
                stop_reason=stop_reason,
                cause=cause,
            )
        )


def _resolve_timeline(
    capture_timeline: bool | RetryTimeline | None,
    on_metric: MetricHook | None,
) -> tuple[RetryTimeline | None, MetricHook | None]:
    if not capture_timeline:
        return None, on_metric

    timeline = capture_timeline if isinstance(capture_timeline, RetryTimeline) else RetryTimeline()
    collector = _TimelineCollector(timeline)

    def hook(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        collector.record(event, attempt, sleep_s, tags)
        if on_metric is not None:
            on_metric(event, attempt, sleep_s, tags)

    return timeline, hook
