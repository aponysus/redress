"""
Optional observability helpers for adapting redress hooks to common backends.

These are intentionally light and dependency-free; they accept user-provided
objects from your observability stack and wrap them into MetricHook-compatible
functions.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from .policy import MetricHook


class PrometheusLabelCounter(Protocol):
    def inc(self) -> None: ...


class PrometheusCounter(Protocol):
    def labels(self, *, event: str, **tags: Any) -> PrometheusLabelCounter: ...


class OtelCounter(Protocol):
    def add(self, amount: int | float, *, attributes: Mapping[str, Any] | None = None) -> None: ...


class OtelMeter(Protocol):
    def create_counter(self, name: str) -> OtelCounter: ...


def _prometheus_label_names(names: Sequence[str] | None, metric: object) -> tuple[str, ...] | None:
    if names is None:
        # prometheus-client stores its declared schema here, including () for
        # unlabeled metrics. Keep legacy forwarding for wrappers without it.
        names = getattr(metric, "_labelnames", None)
    if names is None:
        return None
    if isinstance(names, str):
        raise ValueError("Prometheus label names must be a sequence of names, not a string")
    result = tuple(names)
    if len(set(result)) != len(result):
        raise ValueError("Prometheus label names must be unique")
    return result


def _prometheus_labels(
    event: str, tags: Mapping[str, Any], names: tuple[str, ...]
) -> dict[str, str]:
    values = {name: event if name == "event" else tags.get(name) for name in names}
    return {name: "" if value is None else str(value) for name, value in values.items()}


def prometheus_metric_hook(
    counter: PrometheusCounter,
    *,
    label_names: Sequence[str] | None = None,
) -> MetricHook:
    """
    Wrap a Prometheus Counter into a MetricHook.

    Args:
        counter: Counter exposing ``labels(...).inc()``.
        label_names: Labels declared by the counter. Defaults to the metric's
            declared names for prometheus-client objects. Wrappers without label
            metadata retain legacy forwarding of all tags unless names are given.
            With a known schema, extra tags are ignored, missing or None values
            become empty strings, and other values are converted to strings.
            Use an empty sequence for an unlabeled counter.

    Returns:
        A hook that increments the counter once per event. Ordinary metric
        exceptions are ignored; cancellation and process-exit exceptions propagate.

    Raises:
        ValueError: If label_names is a string or contains duplicate names.
    """
    names = _prometheus_label_names(label_names, counter)

    def hook(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        try:
            if names == ():
                child = cast(PrometheusLabelCounter, counter)
            else:
                labels = (
                    {**tags, "event": event}
                    if names is None
                    else _prometheus_labels(event, tags, names)
                )
                child = counter.labels(**labels)
            child.inc()
        except Exception:
            pass

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
