"""Shared isolation boundary for attempt lifecycle observers."""

from .types import AttemptContext, AttemptHook


def _call_attempt_hook(hook: AttemptHook, ctx: AttemptContext) -> None:
    """Ignore observer errors without swallowing cancellation or process exit."""
    try:
        hook(ctx)
    except Exception:
        pass
