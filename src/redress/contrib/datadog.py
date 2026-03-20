"""Datadog observability helpers."""

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypedDict, cast

from ..events import EventName
from ..policy import MetricHook


class DatadogStatsd(Protocol):
    def increment(
        self, metric: str, value: int = 1, *, tags: Sequence[str] | None = None
    ) -> None: ...

    def histogram(
        self, metric: str, value: float, *, tags: Sequence[str] | None = None
    ) -> None: ...


class DatadogHooks(TypedDict):
    on_metric: MetricHook


def _default_statsd() -> DatadogStatsd:
    try:
        datadog = importlib.import_module("datadog")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("datadog is required for redress.contrib.datadog") from exc
    return cast(DatadogStatsd, datadog.statsd)


def _metric_tags(tags: Mapping[str, Any], constant_tags: Sequence[str]) -> list[str]:
    values = list(constant_tags)
    for key in ("class", "operation", "err", "stop_reason", "cause", "state"):
        value = tags.get(key)
        if value is None:
            continue
        values.append(f"{key}:{value}")
    return values


def datadog_hooks(
    *,
    statsd: DatadogStatsd | None = None,
    prefix: str = "redress",
    constant_tags: Sequence[str] | None = None,
) -> DatadogHooks:
    """
    Return DogStatsD-compatible metric hooks.

    Emits `{prefix}.events` for all events and `{prefix}.retry.sleep_seconds`
    histograms for retry delays.
    """
    statsd = statsd or _default_statsd()
    constant_tags = list(constant_tags or [])

    def on_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        del attempt
        metric_tags = [f"event:{event}", *_metric_tags(tags, constant_tags)]
        statsd.increment(f"{prefix}.events", 1, tags=metric_tags)

        if event == EventName.RETRY.value:
            statsd.histogram(f"{prefix}.retry.sleep_seconds", sleep_s, tags=metric_tags)

    return {"on_metric": on_metric}


__all__ = [
    "DatadogHooks",
    "DatadogStatsd",
    "datadog_hooks",
]
