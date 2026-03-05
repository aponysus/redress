"""FastAPI/Starlette HTTP middleware helpers.

Built on top of `redress.contrib.asgi` and kept here for backward-compatible
imports plus route-template-aware operation naming.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from .asgi import (
    IDEMPOTENT_METHODS,
    AsyncPolicyLike,
    CallKwargsProvider,
    CallNext,
    OperationBuilder,
    PolicyProvider,
    RequestLike,
    SkipPredicate,
    is_idempotent_request,
)
from .asgi import (
    default_operation as _scope_default_operation,
)
from .asgi import (
    retry_middleware as _asgi_retry_middleware,
)

ResponseT = TypeVar("ResponseT")


def _route_path(scope: Mapping[str, Any]) -> str | None:
    route = scope.get("route")
    if route is None:
        return None

    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path

    path_format = getattr(route, "path_format", None)
    if isinstance(path_format, str):
        return path_format

    return None


def default_operation(request: RequestLike) -> str:
    """
    Build an operation name from the HTTP method and route path.

    Uses the router path template when available to avoid high-cardinality
    metrics; falls back to ASGI scope path semantics.
    """
    path = _route_path(request.scope)
    if path is None:
        return _scope_default_operation(request)
    return f"{request.method} {path}"


def retry_middleware(
    policy: AsyncPolicyLike[ResponseT] | None = None,
    *,
    policy_provider: PolicyProvider[ResponseT] | None = None,
    operation: OperationBuilder | None = None,
    skip_if: SkipPredicate | None = None,
    call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
) -> Callable[[RequestLike, CallNext[ResponseT]], Awaitable[ResponseT]]:
    """
    Build a FastAPI middleware function that wraps requests in a retry policy.

    Defaults to route-template-aware operation naming.
    """
    return _asgi_retry_middleware(
        policy,
        policy_provider=policy_provider,
        operation=operation or default_operation,
        skip_if=skip_if,
        call_kwargs=call_kwargs,
    )


__all__ = [
    "IDEMPOTENT_METHODS",
    "AsyncPolicyLike",
    "CallKwargsProvider",
    "CallNext",
    "OperationBuilder",
    "PolicyProvider",
    "RequestLike",
    "SkipPredicate",
    "default_operation",
    "is_idempotent_request",
    "retry_middleware",
]
