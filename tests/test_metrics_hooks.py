# tests/test_metrics_hooks.py

from collections.abc import Mapping

from redress.metrics import otel_metric_hook, prometheus_metric_hook


class _FakePromCounter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def labels(self, *, event: str, **tags: object):
        self.calls.append({"event": event, **tags})
        return self

    def inc(self) -> None:  # pragma: no cover - we track via calls
        return None


class _FakeOtelCounter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def add(self, amount: int | float, *, attributes: Mapping[str, object] | None = None) -> None:
        self.calls.append({"amount": amount, "attributes": dict(attributes or {})})


class _FakeMeter:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.counter = _FakeOtelCounter()

    def create_counter(self, name: str) -> _FakeOtelCounter:
        self.created.append(name)
        return self.counter


def test_prometheus_metric_hook_invokes_labels() -> None:
    counter = _FakePromCounter()
    hook = prometheus_metric_hook(counter)
    hook("retry", 1, 0.5, {"class": "TRANSIENT", "operation": "fetch"})
    assert counter.calls == [{"event": "retry", "class": "TRANSIENT", "operation": "fetch"}]


def test_otel_metric_hook_invokes_add_with_attributes() -> None:
    meter = _FakeMeter()
    hook = otel_metric_hook(meter, name="redress_events")
    hook("success", 2, 0.0, {"operation": "sync"})

    assert meter.created == ["redress_events"]
    assert len(meter.counter.calls) == 1
    call = meter.counter.calls[0]
    assert call["amount"] == 1
    attrs = call["attributes"]
    assert attrs["event"] == "success"
    assert attrs["attempt"] == 2
    assert attrs["sleep_s"] == 0.0
    assert attrs["operation"] == "sync"
