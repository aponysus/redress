"""ASGI integration helpers for Starlette-style HTTP middleware.

This module is framework-agnostic and dependency-free. It targets middleware
hooks that receive `(request, call_next)` and return a response object.

It does not implement raw ASGI `(scope, receive, send)` middleware. Retrying
raw ASGI calls safely requires response buffering, which is framework-specific.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypeVar

T = TypeVar("T")
ResponseT = TypeVar("ResponseT")


class UrlLike(Protocol):
    path: str


class RequestLike(Protocol):
    method: str
    url: UrlLike
    scope: Mapping[str, Any]

    async def body(self) -> bytes: ...


class AsyncPolicyLike(Protocol[T]):
    async def call(self, func: Callable[[], Awaitable[T]], **kwargs: Any) -> T: ...


CallNext = Callable[[RequestLike], Awaitable[T]]
PolicyProvider = Callable[[RequestLike], AsyncPolicyLike[T]]
OperationBuilder = Callable[[RequestLike], str | None]
SkipPredicate = Callable[[RequestLike], bool]
CallKwargsProvider = Callable[[RequestLike], Mapping[str, Any]]

IDEMPOTENT_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PUT"})


def is_idempotent_request(request: RequestLike) -> bool:
    """
    Return True if the request uses an idempotent HTTP method.
    """
    return request.method.upper() in IDEMPOTENT_METHODS


def default_operation(request: RequestLike) -> str:
    """
    Build an operation name from HTTP method and ASGI scope path.

    Uses `scope["path"]` when present. Falls back to `request.url.path`.
    """
    path = request.scope.get("path", None)
    if not isinstance(path, str):
        path = getattr(request.url, "path", None)
    if not isinstance(path, str):
        path = str(request.scope.get("path", ""))
    return f"{request.method} {path}"


# Alias retained for readability when callers want to be explicit that this
# uses ASGI scope path values rather than framework route templates.
scope_operation = default_operation


def retry_middleware(
    policy: AsyncPolicyLike[ResponseT] | None = None,
    *,
    policy_provider: PolicyProvider[ResponseT] | None = None,
    operation: OperationBuilder | None = None,
    skip_if: SkipPredicate | None = None,
    call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
) -> Callable[[RequestLike, CallNext[ResponseT]], Awaitable[ResponseT]]:
    """
    Build HTTP middleware that wraps requests in a retry policy.

    Usage:
        app.middleware("http")(retry_middleware(policy))

    Provide exactly one of `policy` (shared) or `policy_provider` (per-request).
    """
    if (policy is None) == (policy_provider is None):
        raise ValueError("Provide exactly one of policy or policy_provider.")

    operation_builder = operation or default_operation

    async def middleware(request: RequestLike, call_next: CallNext[ResponseT]) -> ResponseT:
        if skip_if is not None and skip_if(request):
            return await call_next(request)

        policy_obj = policy_provider(request) if policy_provider is not None else policy
        if policy_obj is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Retry policy missing.")

        kwargs: dict[str, Any] = {}
        if call_kwargs is not None:
            if callable(call_kwargs):
                kwargs.update(call_kwargs(request))
            else:
                kwargs.update(call_kwargs)

        if "operation" not in kwargs:
            operation_value = operation_builder(request) if operation_builder is not None else None
            if operation_value is not None:
                kwargs["operation"] = operation_value

        async def _call() -> ResponseT:
            return await call_next(request)

        return await policy_obj.call(_call, **kwargs)

    return middleware


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
    "scope_operation",
]
