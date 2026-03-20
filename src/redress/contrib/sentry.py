"""Sentry observability helpers."""

import importlib
from collections.abc import Mapping
from typing import Any, Protocol, TypedDict, cast

from ..events import EventName
from ..policy import LogHook

_CAPTURE_EVENTS = {
    EventName.PERMANENT_FAIL.value,
    EventName.DEADLINE_EXCEEDED.value,
    EventName.MAX_ATTEMPTS_EXCEEDED.value,
    EventName.MAX_UNKNOWN_ATTEMPTS_EXCEEDED.value,
    EventName.NO_STRATEGY_CONFIGURED.value,
    EventName.BUDGET_EXHAUSTED.value,
}


class SentrySdk(Protocol):
    def add_breadcrumb(
        self,
        *,
        category: str,
        message: str,
        level: str,
        data: Mapping[str, Any] | None = None,
    ) -> None: ...

    def capture_message(self, message: str, *, level: str = "error") -> Any: ...


class SentryHooks(TypedDict):
    on_log: LogHook


def _default_sentry() -> SentrySdk:
    try:
        sentry_sdk = importlib.import_module("sentry_sdk")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("sentry-sdk is required for redress.contrib.sentry") from exc
    return cast(SentrySdk, sentry_sdk)


def _breadcrumb_level(event: str) -> str:
    if event == EventName.RETRY.value:
        return "warning"
    if event in _CAPTURE_EVENTS:
        return "error"
    return "info"


def sentry_hooks(
    *,
    sentry: SentrySdk | None = None,
    capture_terminal: bool = True,
) -> SentryHooks:
    """
    Return Sentry-compatible log hooks.

    All events become breadcrumbs. Terminal failure events also emit a captured
    message by default.
    """
    sentry = sentry or _default_sentry()

    def on_log(event: str, fields: dict[str, Any]) -> None:
        level = _breadcrumb_level(event)
        sentry.add_breadcrumb(
            category="redress",
            message=event,
            level=level,
            data=dict(fields),
        )

        if capture_terminal and event in _CAPTURE_EVENTS:
            sentry.capture_message(f"redress.{event}", level="error")

    return {"on_log": on_log}


__all__ = [
    "SentryHooks",
    "SentrySdk",
    "sentry_hooks",
]
