"""Prometheus observability helpers."""

from collections.abc import Mapping
from typing import Any, Protocol, TypedDict

from ..events import EventName
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


def _counter_labels(event: str, tags: Mapping[str, Any]) -> dict[str, Any]:
    return {"event": event, **tags}


def _histogram_labels(tags: Mapping[str, Any]) -> dict[str, Any]:
    return dict(tags)


def prometheus_hooks(
    *,
    events: PrometheusCounter,
    retry_sleep_seconds: PrometheusHistogram | None = None,
) -> PrometheusHooks:
    """
    Return Prometheus-compatible metric hooks.

    `events` should be a Counter labeled by `event` plus any desired tags.
    `retry_sleep_seconds`, when provided, observes retry sleep durations with
    the same tag set minus the event label.
    """

    def on_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        del attempt
        events.labels(**_counter_labels(event, tags)).inc()

        if retry_sleep_seconds is not None and event == EventName.RETRY.value:
            retry_sleep_seconds.labels(**_histogram_labels(tags)).observe(sleep_s)

    return {"on_metric": on_metric}


__all__ = [
    "PrometheusCounter",
    "PrometheusHooks",
    "PrometheusHistogram",
    "PrometheusLabelCounter",
    "PrometheusLabelHistogram",
    "prometheus_hooks",
]
