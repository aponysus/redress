from collections.abc import Mapping

import redress.contrib.otel as otel


class _FakeSpan:
    def __init__(self, name: str, attributes: Mapping[str, object] | None) -> None:
        self.name = name
        self.attributes = dict(attributes or {})
        self.events: list[dict[str, object]] = []
        self.set_attributes: dict[str, object] = {}
        self.ended = False

    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None:
        self.events.append({"name": name, "attributes": dict(attributes or {})})

    def set_attribute(self, key: str, value: object) -> None:
        self.set_attributes[key] = value

    def end(self) -> None:
        self.ended = True


class _FakeTracer:
    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []

    def start_span(self, name: str, *, attributes: Mapping[str, object] | None = None) -> _FakeSpan:
        span = _FakeSpan(name, attributes)
        self.spans.append(span)
        return span


class _FakeCounter:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict[str, object]] = []

    def add(self, amount: int | float, *, attributes: Mapping[str, object] | None = None) -> None:
        self.calls.append({"amount": amount, "attributes": dict(attributes or {})})


class _FakeHistogram:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict[str, object]] = []

    def record(
        self, amount: int | float, *, attributes: Mapping[str, object] | None = None
    ) -> None:
        self.calls.append({"amount": amount, "attributes": dict(attributes or {})})


class _FakeMeter:
    def __init__(self) -> None:
        self.counters: dict[str, _FakeCounter] = {}
        self.histograms: dict[str, _FakeHistogram] = {}

    def create_counter(self, name: str) -> _FakeCounter:
        counter = _FakeCounter(name)
        self.counters[name] = counter
        return counter

    def create_histogram(self, name: str) -> _FakeHistogram:
        histogram = _FakeHistogram(name)
        self.histograms[name] = histogram
        return histogram


def test_otel_hooks_emit_metrics(monkeypatch) -> None:
    otel._state_var.set(None)
    meter = _FakeMeter()
    tracer = _FakeTracer()
    hooks = otel.otel_hooks(tracer=tracer, meter=meter)
    on_metric = hooks["on_metric"]

    times = iter([100.0, 105.0])
    monkeypatch.setattr(otel.time, "monotonic", lambda: next(times))

    on_metric("retry", 1, 0.5, {"class": "RATE_LIMIT", "operation": "fetch"})
    on_metric("success", 2, 0.0, {"class": "RATE_LIMIT", "operation": "fetch"})

    retries = meter.counters["redress.retries"]
    assert len(retries.calls) == 1
    retry_attrs = retries.calls[0]["attributes"]
    assert retry_attrs["error.class"] == "RATE_LIMIT"
    assert retry_attrs["retry.attempt"] == 1
    assert retry_attrs["operation"] == "fetch"

    success = meter.counters["redress.retry.success_after_retries"]
    assert len(success.calls) == 1
    success_attrs = success.calls[0]["attributes"]
    assert success_attrs["error.class"] == "RATE_LIMIT"
    assert success_attrs["retry.attempt"] == 2
    assert success_attrs["operation"] == "fetch"

    duration = meter.histograms["redress.retry.duration"]
    assert len(duration.calls) == 1
    assert duration.calls[0]["amount"] == 5.0


def test_otel_hooks_emit_span_events() -> None:
    otel._state_var.set(None)
    meter = _FakeMeter()
    tracer = _FakeTracer()
    hooks = otel.otel_hooks(tracer=tracer, meter=meter)
    on_log = hooks["on_log"]

    on_log("retry", {"attempt": 1, "sleep_s": 0.5, "class": "RATE_LIMIT", "operation": "fetch"})
    on_log("success", {"attempt": 2, "sleep_s": 0.0, "class": "RATE_LIMIT", "operation": "fetch"})

    assert len(tracer.spans) == 1
    span = tracer.spans[0]
    assert span.name == "fetch"
    assert [event["name"] for event in span.events] == ["retry", "success"]
    for event in span.events:
        attrs = event["attributes"]
        assert attrs["error.class"] == "RATE_LIMIT"
        assert attrs["operation"] == "fetch"
        assert attrs["retry.attempt"] in (1, 2)
    assert span.set_attributes["retry.attempts"] == 2
    assert span.ended is True


def test_otel_hooks_emit_circuit_state_metric() -> None:
    otel._state_var.set(None)
    meter = _FakeMeter()
    hooks = otel.otel_hooks(tracer=_FakeTracer(), meter=meter)
    on_metric = hooks["on_metric"]

    on_metric(
        "circuit_opened",
        0,
        0.0,
        {"state": "open", "class": "RATE_LIMIT", "operation": "fetch"},
    )

    circuit = meter.counters["redress.circuit.state"]
    assert len(circuit.calls) == 1
    attrs = circuit.calls[0]["attributes"]
    assert attrs["circuit.state"] == "open"
    assert attrs["error.class"] == "RATE_LIMIT"
    assert attrs["operation"] == "fetch"
