import contextvars
import importlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict, cast

from ..policy import LogHook, MetricHook


class OtelSpan(Protocol):
    def add_event(self, name: str, attributes: Mapping[str, Any] | None = None) -> None: ...

    def set_attribute(self, key: str, value: Any) -> None: ...

    def end(self) -> None: ...


class OtelTracer(Protocol):
    def start_span(
        self, name: str, *, attributes: Mapping[str, Any] | None = None
    ) -> OtelSpan: ...


class OtelCounter(Protocol):
    def add(self, amount: int | float, *, attributes: Mapping[str, Any] | None = None) -> None: ...


class OtelHistogram(Protocol):
    def record(self, amount: int | float, *, attributes: Mapping[str, Any] | None = None) -> None: ...


class OtelMeter(Protocol):
    def create_counter(self, name: str) -> OtelCounter: ...

    def create_histogram(self, name: str) -> OtelHistogram: ...


_TERMINAL_EVENTS = {
    "success",
    "permanent_fail",
    "deadline_exceeded",
    "max_attempts_exceeded",
    "max_unknown_attempts_exceeded",
    "no_strategy_configured",
}

_CIRCUIT_EVENTS = {
    "circuit_opened",
    "circuit_half_open",
    "circuit_closed",
    "circuit_rejected",
}


@dataclass
class _OtelState:
    span: OtelSpan | None = None
    started_at: float | None = None
    last_class: str | None = None
    operation: str | None = None


_state_var: contextvars.ContextVar[_OtelState | None] = contextvars.ContextVar(
    "redress_otel_state", default=None
)


def _get_state() -> _OtelState:
    state = _state_var.get()
    if state is None:
        state = _OtelState()
        _state_var.set(state)
    return state


def _default_tracer() -> OtelTracer:
    try:
        trace = importlib.import_module("opentelemetry.trace")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("opentelemetry-api is required for redress.contrib.otel") from exc
    return cast(OtelTracer, trace.get_tracer("redress"))


def _default_meter() -> OtelMeter:
    try:
        metrics = importlib.import_module("opentelemetry.metrics")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("opentelemetry-api is required for redress.contrib.otel") from exc
    return cast(OtelMeter, metrics.get_meter("redress"))


def _update_state(state: _OtelState, attempt: int, tags: Mapping[str, Any]) -> None:
    if attempt > 0 and state.started_at is None:
        state.started_at = time.monotonic()

    klass = tags.get("class")
    if isinstance(klass, str):
        state.last_class = klass

    operation = tags.get("operation")
    if isinstance(operation, str):
        state.operation = operation


def _build_attributes(
    *,
    event: str,
    attempt: int,
    tags: Mapping[str, Any],
    state: _OtelState,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {"retry.attempt": attempt}

    operation = tags.get("operation") or state.operation
    if operation is not None:
        attrs["operation"] = operation

    error_class = tags.get("class") or state.last_class or "unknown"
    attrs["error.class"] = error_class

    circuit_state = tags.get("state")
    if isinstance(circuit_state, str):
        attrs["circuit.state"] = circuit_state

    return attrs


class OtelHooks(TypedDict):
    on_metric: MetricHook
    on_log: LogHook


def otel_hooks(
    *,
    tracer: OtelTracer | None = None,
    meter: OtelMeter | None = None,
) -> OtelHooks:
    """
    Return OpenTelemetry-compatible metric + log hooks.

    Usage:
        policy.call(func, **otel_hooks(...))
    """
    tracer = tracer or _default_tracer()
    meter = meter or _default_meter()

    retries = meter.create_counter("redress.retries")
    retry_duration = meter.create_histogram("redress.retry.duration")
    success_after_retries = meter.create_counter("redress.retry.success_after_retries")
    circuit_state = meter.create_counter("redress.circuit.state")

    def on_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        if event in _CIRCUIT_EVENTS:
            state = _get_state()
            attrs = _build_attributes(event=event, attempt=attempt, tags=tags, state=state)
            circuit_state.add(1, attributes=attrs)
            return

        state = _get_state()
        _update_state(state, attempt, tags)
        attrs = _build_attributes(event=event, attempt=attempt, tags=tags, state=state)

        if event == "retry":
            retries.add(1, attributes=attrs)

        if event == "success" and attempt > 1:
            success_after_retries.add(1, attributes=attrs)

        if event in _TERMINAL_EVENTS and attempt > 0 and state.started_at is not None:
            duration_s = max(0.0, time.monotonic() - state.started_at)
            retry_duration.record(duration_s, attributes=attrs)
            if state.span is None:
                _state_var.set(None)

    def on_log(event: str, fields: dict[str, Any]) -> None:
        if event in _CIRCUIT_EVENTS:
            return

        attempt = int(fields.get("attempt", 0))
        if attempt <= 0:
            return

        state = _get_state()
        _update_state(state, attempt, fields)
        attrs = _build_attributes(event=event, attempt=attempt, tags=fields, state=state)

        if state.span is None:
            name = state.operation or "redress.retry"
            span_attrs: dict[str, Any] | None = None
            if state.operation is not None:
                span_attrs = {"operation": state.operation}
            state.span = tracer.start_span(name, attributes=span_attrs)

        state.span.add_event(event, attributes=attrs)

        if event in _TERMINAL_EVENTS:
            state.span.set_attribute("retry.attempts", attempt)
            state.span.end()
            _state_var.set(None)

    return {"on_metric": on_metric, "on_log": on_log}
