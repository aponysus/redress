"""Optional redis-py classifier."""

import importlib

from ..classify import default_classifier
from ..errors import ErrorClass


def redis_classifier(exc: BaseException) -> ErrorClass:
    """
    Classify redis-py exceptions into ErrorClass.

    This helper is optional and degrades gracefully when redis is unavailable.
    """
    try:
        redis_exc = importlib.import_module("redis.exceptions")
    except Exception:
        return default_classifier(exc)

    readonly_exc = getattr(redis_exc, "ReadOnlyError", None)
    if (
        readonly_exc is not None
        and isinstance(readonly_exc, type)
        and isinstance(exc, readonly_exc)
    ):
        return ErrorClass.CONCURRENCY

    auth_exc = getattr(redis_exc, "AuthenticationError", None)
    if auth_exc is not None and isinstance(auth_exc, type) and isinstance(exc, auth_exc):
        return ErrorClass.AUTH

    perm_exc = getattr(redis_exc, "AuthorizationError", None)
    if perm_exc is not None and isinstance(perm_exc, type) and isinstance(exc, perm_exc):
        return ErrorClass.PERMISSION

    timeout_exc = getattr(redis_exc, "TimeoutError", None)
    if timeout_exc is not None and isinstance(timeout_exc, type) and isinstance(exc, timeout_exc):
        return ErrorClass.TRANSIENT

    connection_exc = getattr(redis_exc, "ConnectionError", None)
    if (
        connection_exc is not None
        and isinstance(connection_exc, type)
        and isinstance(exc, connection_exc)
    ):
        return ErrorClass.TRANSIENT

    busy_exc = getattr(redis_exc, "BusyLoadingError", None)
    if busy_exc is not None and isinstance(busy_exc, type) and isinstance(exc, busy_exc):
        return ErrorClass.TRANSIENT

    return default_classifier(exc)
