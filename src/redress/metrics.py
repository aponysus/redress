"""
Optional observability helpers for adapting redress hooks to common backends.

These are intentionally light and dependency-free; they accept user-provided
objects from your observability stack and wrap them into MetricHook-compatible
functions.
"""

from collections.abc import Mapping
from typing import Any, Protocol

from .policy import MetricHook


class PrometheusLabelCounter(Protocol):
    def inc(self) -> None: ...


class PrometheusCounter(Protocol):
    def labels(self, *, event: str, **tags: Any) -> PrometheusLabelCounter: ...


class OtelCounter(Protocol):
    def add(self, amount: int | float, *, attributes: Mapping[str, Any] | None = None) -> None: ...


class OtelMeter(Protocol):
    def create_counter(self, name: str) -> OtelCounter: ...


def prometheus_metric_hook(counter: PrometheusCounter) -> MetricHook:
    """
    Wrap a Prometheus Counter into a MetricHook.

    The counter is expected to expose .labels(event=..., **tags).inc().
    """

    def hook(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        counter.labels(event=event, **tags).inc()

    return hook


def otel_metric_hook(meter: OtelMeter, name: str = "redress_attempts") -> MetricHook:
    """
    Example OpenTelemetry-style hook (pseudo-code).

    The meter is expected to be an OTEL Meter that can create a counter with
    add() and attributes/event arguments. No OTEL dependency is imported here.
    """

    counter = meter.create_counter(name)

    def hook(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        attributes = {"event": event, "attempt": attempt, "sleep_s": sleep_s, **tags}
        counter.add(1, attributes=attributes)

    return hook
