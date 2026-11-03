"""Prometheus observability helpers."""

from collections.abc import Sequence
from typing import Any, Protocol, TypedDict, cast

from ..events import EventName
from ..metrics import _prometheus_label_names, _prometheus_labels, prometheus_metric_hook
from ..policy import MetricHook


class PrometheusLabelCounter(Protocol):
    def inc(self, amount: float = 1.0) -> None: ...


class PrometheusLabelHistogram(Protocol):
    def observe(self, amount: float) -> None: ...


class PrometheusCounter(Protocol):
    def labels(self, **labels: Any) -> PrometheusLabelCounter: ...


class PrometheusHistogram(Protocol):
    def labels(self, **labels: Any) -> PrometheusLabelHistogram: ...


class PrometheusHooks(TypedDict):
    on_metric: MetricHook


def prometheus_hooks(
    *,
    events: PrometheusCounter,
    retry_sleep_seconds: PrometheusHistogram | None = None,
    event_labels: Sequence[str] | None = None,
    retry_sleep_labels: Sequence[str] | None = None,
) -> PrometheusHooks:
    """
    Return Prometheus-compatible metric hooks.

    Args:
        events: Counter incremented for every lifecycle event.
        retry_sleep_seconds: Optional histogram of scheduled retry delays.
        event_labels: Counter labels; defaults to the metric's declared names.
        retry_sleep_labels: Histogram labels; defaults to the metric's declared names.

    Only declared or explicitly configured labels are passed to each metric.
    Wrappers without label metadata retain legacy forwarding of all tags unless
    names are given. With a known schema, missing or None values
    become empty strings; other values are converted to strings. The ``event``
    label always uses the event argument. Use an empty sequence for an unlabeled
    metric. Counter and histogram failures are isolated independently.

    Returns:
        An on_metric hook for use with sync or async policies.

    Raises:
        ValueError: If either label sequence is a string or contains duplicates.
    """
    counter_hook = prometheus_metric_hook(events, label_names=event_labels)
    histogram_names = _prometheus_label_names(retry_sleep_labels, retry_sleep_seconds)

    def on_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        counter_hook(event, attempt, sleep_s, tags)

        if retry_sleep_seconds is not None and event == EventName.RETRY.value:
            try:
                if histogram_names == ():
                    child = cast(PrometheusLabelHistogram, retry_sleep_seconds)
                else:
                    labels = (
                        dict(tags)
                        if histogram_names is None
                        else _prometheus_labels(event, tags, histogram_names)
                    )
                    child = retry_sleep_seconds.labels(**labels)
                child.observe(sleep_s)
            except Exception:
                pass

    return {"on_metric": on_metric}


__all__ = [
    "PrometheusCounter",
    "PrometheusHooks",
    "PrometheusHistogram",
    "PrometheusLabelCounter",
    "PrometheusLabelHistogram",
    "prometheus_hooks",
]
