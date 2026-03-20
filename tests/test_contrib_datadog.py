from collections.abc import Sequence

import redress.contrib.datadog as datadog


class _FakeStatsd:
    def __init__(self) -> None:
        self.increment_calls: list[dict[str, object]] = []
        self.histogram_calls: list[dict[str, object]] = []

    def increment(self, metric: str, value: int = 1, *, tags: Sequence[str] | None = None) -> None:
        self.increment_calls.append({"metric": metric, "value": value, "tags": list(tags or [])})

    def histogram(self, metric: str, value: float, *, tags: Sequence[str] | None = None) -> None:
        self.histogram_calls.append({"metric": metric, "value": value, "tags": list(tags or [])})


def test_datadog_hooks_emit_metrics_and_retry_histogram() -> None:
    statsd = _FakeStatsd()
    hooks = datadog.datadog_hooks(
        statsd=statsd,
        prefix="svc.redress",
        constant_tags=["env:test"],
    )
    on_metric = hooks["on_metric"]

    on_metric("retry", 1, 0.5, {"class": "RATE_LIMIT", "operation": "fetch"})
    on_metric("success", 2, 0.0, {"class": "RATE_LIMIT", "operation": "fetch"})

    assert statsd.increment_calls == [
        {
            "metric": "svc.redress.events",
            "value": 1,
            "tags": ["event:retry", "env:test", "class:RATE_LIMIT", "operation:fetch"],
        },
        {
            "metric": "svc.redress.events",
            "value": 1,
            "tags": ["event:success", "env:test", "class:RATE_LIMIT", "operation:fetch"],
        },
    ]
    assert statsd.histogram_calls == [
        {
            "metric": "svc.redress.retry.sleep_seconds",
            "value": 0.5,
            "tags": ["event:retry", "env:test", "class:RATE_LIMIT", "operation:fetch"],
        }
    ]


def test_datadog_default_import(monkeypatch) -> None:
    statsd = _FakeStatsd()

    class _FakeModule:
        def __init__(self, statsd_obj: _FakeStatsd) -> None:
            self.statsd = statsd_obj

    monkeypatch.setattr(datadog.importlib, "import_module", lambda name: _FakeModule(statsd))
    hooks = datadog.datadog_hooks()
    hooks["on_metric"]("success", 1, 0.0, {"operation": "op"})

    assert statsd.increment_calls == [
        {"metric": "redress.events", "value": 1, "tags": ["event:success", "operation:op"]}
    ]


def test_datadog_public_exports_stable() -> None:
    assert datadog.__all__ == [
        "DatadogHooks",
        "DatadogStatsd",
        "datadog_hooks",
    ]
