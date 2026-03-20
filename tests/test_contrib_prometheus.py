import redress.contrib.prometheus as prometheus


class _FakeCounterChild:
    def __init__(self, calls: list[dict[str, object]], labels: dict[str, object]) -> None:
        self.calls = calls
        self.labels = labels

    def inc(self, amount: float = 1.0) -> None:
        self.calls.append({"labels": self.labels, "amount": amount})


class _FakeHistogramChild:
    def __init__(self, calls: list[dict[str, object]], labels: dict[str, object]) -> None:
        self.calls = calls
        self.labels = labels

    def observe(self, amount: float) -> None:
        self.calls.append({"labels": self.labels, "amount": amount})


class _FakeCounter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def labels(self, **labels: object) -> _FakeCounterChild:
        return _FakeCounterChild(self.calls, dict(labels))


class _FakeHistogram:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def labels(self, **labels: object) -> _FakeHistogramChild:
        return _FakeHistogramChild(self.calls, dict(labels))


def test_prometheus_hooks_emit_counter_and_retry_histogram() -> None:
    counter = _FakeCounter()
    histogram = _FakeHistogram()
    hooks = prometheus.prometheus_hooks(events=counter, retry_sleep_seconds=histogram)
    on_metric = hooks["on_metric"]

    on_metric("retry", 1, 0.5, {"class": "RATE_LIMIT", "operation": "fetch"})
    on_metric("success", 2, 0.0, {"class": "RATE_LIMIT", "operation": "fetch"})

    assert counter.calls == [
        {"labels": {"event": "retry", "class": "RATE_LIMIT", "operation": "fetch"}, "amount": 1.0},
        {"labels": {"event": "success", "class": "RATE_LIMIT", "operation": "fetch"}, "amount": 1.0},
    ]
    assert histogram.calls == [
        {"labels": {"class": "RATE_LIMIT", "operation": "fetch"}, "amount": 0.5}
    ]


def test_prometheus_public_exports_stable() -> None:
    assert prometheus.__all__ == [
        "PrometheusCounter",
        "PrometheusHooks",
        "PrometheusHistogram",
        "PrometheusLabelCounter",
        "PrometheusLabelHistogram",
        "prometheus_hooks",
    ]
