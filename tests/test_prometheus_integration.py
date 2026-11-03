"""Real-client regressions; install the prometheus extra to run these tests."""

import asyncio
import re
import runpy
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from redress import (
    AsyncPolicy,
    AsyncRetry,
    CircuitBreaker,
    EventName,
    Policy,
    Retry,
    StopReason,
    default_classifier,
)
from redress.contrib.prometheus import PrometheusHooks, prometheus_hooks
from redress.metrics import prometheus_metric_hook

prometheus = pytest.importorskip("prometheus_client")


class _LabelsOnly:
    """A protocol-compatible wrapper that does not expose metric metadata."""

    def __init__(self, metric: Any) -> None:
        self.metric = metric

    def labels(self, **labels: Any) -> Any:
        return self.metric.labels(**labels)


@pytest.fixture
def metrics() -> tuple[Any, PrometheusHooks]:
    registry = prometheus.CollectorRegistry()
    counter = prometheus.Counter(
        "events", "Lifecycle events", ["event", "class", "operation"], registry=registry
    )
    histogram = prometheus.Histogram(
        "delays", "Scheduled delays", ["class", "operation"], registry=registry
    )
    return registry, prometheus_hooks(events=counter, retry_sleep_seconds=histogram)


@pytest.fixture(params=["sync", "async"])
def policy(request: pytest.FixtureRequest) -> Policy | AsyncPolicy:
    async def no_sleep(_: float) -> None:
        pass

    if request.param == "async":
        return AsyncPolicy(
            retry=AsyncRetry(
                classifier=default_classifier,
                strategy=lambda ctx: 0.25,
                max_attempts=2,
                sleeper=no_sleep,
            )
        )
    return Policy(
        retry=Retry(
            classifier=default_classifier,
            strategy=lambda ctx: 0.25,
            max_attempts=2,
            sleeper=lambda _: None,
        )
    )


def _invoke(
    policy: Policy | AsyncPolicy, method: str, work: Callable[[], str], **kwargs: Any
) -> Any:
    if isinstance(policy, AsyncPolicy):

        async def async_work() -> str:
            return work()

        return asyncio.run(getattr(policy, method)(async_work, **kwargs))
    return getattr(policy, method)(work, **kwargs)


def _fail() -> str:
    raise ConnectionError("unavailable")


@pytest.mark.parametrize("method", ["call", "execute"])
@pytest.mark.parametrize("operation", [None, "fetch"])
def test_retry_then_success_records_samples(policy, metrics, method, operation) -> None:
    registry, hooks = metrics
    attempts = 0

    def recover() -> str:
        nonlocal attempts
        attempts += 1
        return _fail() if attempts == 1 else "ok"

    result = _invoke(policy, method, recover, operation=operation, **hooks)

    assert (result.value if method == "execute" else result) == "ok"
    assert attempts == 2
    tags = {"class": "TRANSIENT", "operation": operation or ""}
    assert registry.get_sample_value("events_total", {"event": "retry", **tags}) == 1
    assert (
        registry.get_sample_value(
            "events_total", {"event": "success", "class": "", "operation": operation or ""}
        )
        == 1
    )
    assert registry.get_sample_value("delays_count", tags) == 1
    assert registry.get_sample_value("delays_sum", tags) == 0.25


@pytest.mark.parametrize("adapter", ["core", "contrib"])
@pytest.mark.parametrize("operation", [None, "fetch"])
def test_omitted_configuration_preserves_existing_counter_schema(
    policy, adapter, operation
) -> None:
    registry = prometheus.CollectorRegistry()
    labels = ("event",) if operation is None else ("event", "operation")
    counter = prometheus.Counter("events", "Events", labels, registry=registry)
    hook = (
        prometheus_metric_hook(counter)
        if adapter == "core"
        else prometheus_hooks(events=counter)["on_metric"]
    )
    assert _invoke(policy, "call", lambda: "ok", on_metric=hook, operation=operation) == "ok"
    tags = {} if operation is None else {"operation": operation}
    assert registry.get_sample_value("events_total", {"event": "success", **tags}) == 1

    attempts = 0

    def recover() -> str:
        nonlocal attempts
        attempts += 1
        return _fail() if attempts == 1 else "ok"

    assert _invoke(policy, "call", recover, on_metric=hook, operation=operation) == "ok"
    assert attempts == 2
    assert registry.get_sample_value("events_total", {"event": "retry", **tags}) == 1
    assert registry.get_sample_value("events_total", {"event": "success", **tags}) == 2


def test_exhaustion_and_abort_record_terminal_events(policy, metrics) -> None:
    registry, hooks = metrics
    outcome = _invoke(policy, "execute", _fail, operation="fetch", **hooks)
    assert outcome.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
    assert isinstance(outcome.last_exception, ConnectionError)
    tags = {"class": "TRANSIENT", "operation": "fetch"}
    assert registry.get_sample_value("events_total", {"event": "retry", **tags}) == 1
    assert (
        registry.get_sample_value("events_total", {"event": "max_attempts_exceeded", **tags}) == 1
    )
    assert registry.get_sample_value("delays_count", tags) == 1
    assert registry.get_sample_value("delays_sum", tags) == 0.25

    outcome = _invoke(policy, "execute", _fail, abort_if=lambda: True, **hooks)
    assert outcome.stop_reason == StopReason.ABORTED
    assert outcome.attempts == 0
    assert (
        registry.get_sample_value(
            "events_total", {"event": "aborted", "class": "", "operation": ""}
        )
        == 1
    )
    assert registry.get_sample_value("delays_count", {"class": "", "operation": ""}) is None


def test_breaker_transitions_and_rejection_record_samples(policy, metrics) -> None:
    registry, hooks = metrics
    now = 0.0
    policy.circuit_breaker = CircuitBreaker(
        failure_threshold=1, window_s=10, recovery_timeout_s=2, clock=lambda: now
    )
    failed = _invoke(policy, "execute", _fail, operation="fetch", **hooks)
    assert failed.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
    rejected = _invoke(policy, "execute", lambda: "ok", operation="fetch", **hooks)
    assert rejected.attempts == 0
    now = 3.0
    recovered = _invoke(policy, "execute", lambda: "ok", operation="fetch", **hooks)
    assert recovered.value == "ok"

    for event in ("circuit_opened", "circuit_rejected", "circuit_half_open", "circuit_closed"):
        assert (
            registry.get_sample_value(
                "events_total",
                {
                    "event": event,
                    "class": "TRANSIENT" if event == "circuit_opened" else "",
                    "operation": "fetch",
                },
            )
            == 1
        )
    assert (
        registry.get_sample_value("delays_count", {"class": "TRANSIENT", "operation": "fetch"}) == 1
    )


@pytest.mark.parametrize("adapter", ["core", "contrib"])
def test_all_events_support_custom_counter_labels(adapter) -> None:
    registry = prometheus.CollectorRegistry()
    counter = prometheus.Counter("events", "Events", ["event", "err", "state"], registry=registry)
    names = ["event", "err", "state"]
    hook = (
        prometheus_metric_hook(counter, label_names=names)
        if adapter == "core"
        else prometheus_hooks(events=counter, event_labels=names)["on_metric"]
    )
    names.append("operation")  # Changing caller configuration must not change the metric schema.
    tags = {"event": "wrong", "state": 123, "err": None, "operation": "fetch"}
    for event in EventName:
        hook(event.value, 1, 0.25, tags)
        assert (
            registry.get_sample_value(
                "events_total", {"event": event.value, "err": "", "state": "123"}
            )
            == 1
        )
    assert tags == {"event": "wrong", "state": 123, "err": None, "operation": "fetch"}


@pytest.mark.parametrize("configure_labels", [False, True])
def test_histogram_schema_is_independent_of_counter_schema(configure_labels) -> None:
    registry = prometheus.CollectorRegistry()
    counter = prometheus.Counter("events", "Events", ["event"], registry=registry)
    histogram = prometheus.Histogram("delays", "Delays", ["cause", "operation"], registry=registry)
    options = (
        {"event_labels": ("event",), "retry_sleep_labels": ("cause", "operation")}
        if configure_labels
        else {}
    )
    hook = prometheus_hooks(
        events=counter,
        retry_sleep_seconds=histogram,
        **options,
    )["on_metric"]
    hook("retry", 1, 0.25, {"cause": "result", "class": "TRANSIENT"})
    hook("success", 2, 0.0, {})
    assert registry.get_sample_value("events_total", {"event": "retry"}) == 1
    assert registry.get_sample_value("events_total", {"event": "success"}) == 1
    assert registry.get_sample_value("delays_count", {"cause": "result", "operation": ""}) == 1
    assert registry.get_sample_value("delays_sum", {"cause": "result", "operation": ""}) == 0.25


@pytest.mark.parametrize("configure_labels", [False, True])
def test_unlabeled_metrics(configure_labels) -> None:
    registry = prometheus.CollectorRegistry()
    counter = prometheus.Counter("events", "Events", registry=registry)
    histogram = prometheus.Histogram("delays", "Delays", registry=registry)
    options = {"event_labels": (), "retry_sleep_labels": ()} if configure_labels else {}
    hook = prometheus_hooks(
        events=counter,
        retry_sleep_seconds=histogram,
        **options,
    )["on_metric"]
    hook("retry", 1, 0.25, {"class": "TRANSIENT", "operation": "fetch"})
    hook("success", 2, 0.0, {})
    assert registry.get_sample_value("events_total") == 2
    assert registry.get_sample_value("delays_count") == 1
    assert registry.get_sample_value("delays_sum") == 0.25


@pytest.mark.parametrize("adapter", ["core", "contrib"])
def test_wrappers_without_metadata_keep_legacy_tag_forwarding(adapter) -> None:
    registry = prometheus.CollectorRegistry()
    counter = _LabelsOnly(
        prometheus.Counter(
            "events",
            "Events",
            ["event", "operation", "cause", "err"],
            registry=registry,
        )
    )
    histogram = _LabelsOnly(
        prometheus.Histogram(
            "delays",
            "Delays",
            ["operation", "cause", "err"],
            registry=registry,
        )
    )
    hook = (
        prometheus_metric_hook(counter)
        if adapter == "core"
        else prometheus_hooks(events=counter, retry_sleep_seconds=histogram)["on_metric"]
    )
    tags = {"operation": "fetch", "cause": "exception", "err": "ConnectionError"}
    hook("retry", 1, 0.25, tags)
    assert registry.get_sample_value("events_total", {"event": "retry", **tags}) == 1
    if adapter == "contrib":
        assert registry.get_sample_value("delays_count", tags) == 1
        assert registry.get_sample_value("delays_sum", tags) == 0.25


@pytest.mark.parametrize("sink", ["counter", "histogram"])
@pytest.mark.parametrize("stage", ["labels", "write"])
def test_metric_failures_are_isolated_independently(monkeypatch, sink, stage) -> None:
    registry = prometheus.CollectorRegistry()
    counter = prometheus.Counter("events", "Events", ["event"], registry=registry)
    histogram = prometheus.Histogram("delays", "Delays", ["operation"], registry=registry)
    metric = counter if sink == "counter" else histogram
    child = counter.labels(event="retry") if sink == "counter" else histogram.labels(operation="")

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ValueError("metric failed")

    if stage == "labels":
        monkeypatch.setattr(metric, "labels", fail)
    else:
        monkeypatch.setattr(child, "inc" if sink == "counter" else "observe", fail)
    hook = prometheus_hooks(
        events=counter,
        retry_sleep_seconds=histogram,
        event_labels=("event",),
        retry_sleep_labels=("operation",),
    )["on_metric"]
    hook("retry", 1, 0.25, {})
    if sink == "counter":
        assert registry.get_sample_value("delays_count", {"operation": ""}) == 1
        assert registry.get_sample_value("delays_sum", {"operation": ""}) == 0.25
    else:
        assert registry.get_sample_value("events_total", {"event": "retry"}) == 1


@pytest.mark.parametrize("sink", ["counter", "histogram"])
@pytest.mark.parametrize("error", [asyncio.CancelledError, KeyboardInterrupt, SystemExit])
def test_metric_interruptions_propagate(monkeypatch, sink, error) -> None:
    registry = prometheus.CollectorRegistry()
    counter = prometheus.Counter("events", "Events", registry=registry)
    histogram = prometheus.Histogram("delays", "Delays", registry=registry)

    def interrupt(*args: Any, **kwargs: Any) -> None:
        raise error()

    monkeypatch.setattr(
        counter if sink == "counter" else histogram,
        "inc" if sink == "counter" else "observe",
        interrupt,
    )
    hook = prometheus_hooks(
        events=counter,
        retry_sleep_seconds=histogram,
        event_labels=(),
        retry_sleep_labels=(),
    )["on_metric"]
    with pytest.raises(error):
        hook("retry", 1, 0.25, {})


@pytest.mark.parametrize("names", ["event", ("event", "event")])
@pytest.mark.parametrize("option", ["event_labels", "retry_sleep_labels"])
def test_invalid_label_configuration_rejected_at_creation(names, option) -> None:
    counter = prometheus.Counter("events", "Events", registry=prometheus.CollectorRegistry())
    with pytest.raises(ValueError, match="Prometheus label names"):
        prometheus_hooks(events=counter, **{option: names})


def test_documented_example_records_samples() -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "snippets" / "prometheus_contrib.py"
    # Running twice also proves the example does not pollute the default registry.
    for _ in range(2):
        namespace = runpy.run_path(str(path))
        registry = namespace["registry"]
        assert namespace["result"] == "ok"
        tags = {"class": "TRANSIENT", "operation": "sync_user"}
        assert registry.get_sample_value("redress_events_total", {"event": "retry", **tags}) == 1
        assert (
            registry.get_sample_value(
                "redress_events_total",
                {
                    "event": "success",
                    "class": "",
                    "operation": "sync_user",
                },
            )
            == 1
        )
        assert registry.get_sample_value("redress_retry_sleep_seconds_count", tags) == 1
        assert registry.get_sample_value("redress_retry_sleep_seconds_sum", tags) == 0.25


def test_reference_flow_prometheus_configuration(monkeypatch) -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "reference-flows.md"
    examples = [
        code
        for code in re.findall(r"```python\n(.*?)```", path.read_text(), re.DOTALL)
        if "from redress.metrics import prometheus_metric_hook" in code
    ]
    assert len(examples) == 1
    registry = prometheus.CollectorRegistry()
    monkeypatch.setattr(prometheus, "Counter", partial(prometheus.Counter, registry=registry))
    policy = Policy(
        retry=Retry(
            classifier=default_classifier,
            strategy=lambda ctx: 0.25,
            max_attempts=2,
            sleeper=lambda _: None,
        )
    )
    attempts = 0

    def work() -> str:
        nonlocal attempts
        attempts += 1
        return _fail() if attempts == 1 else "ok"

    exec(compile(examples[0], str(path), "exec"), {"policy": policy, "work": work})

    assert attempts == 2
    assert (
        registry.get_sample_value(
            "redress_events_total",
            {
                "event": "retry",
                "class": "TRANSIENT",
                "operation": "sync_user",
                "err": "ConnectionError",
            },
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "redress_events_total",
            {
                "event": "success",
                "class": "",
                "operation": "sync_user",
                "err": "",
            },
        )
        == 1
    )
