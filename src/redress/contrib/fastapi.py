"""FastAPI integration helpers.

This module is dependency-free; it assumes FastAPI is installed in the
application environment but avoids importing it so `redress` remains
lightweight. The middleware returned here retries the *entire* request
handler, so only use it for idempotent endpoints.
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
    metrics; falls back to the raw request path.
    """
    path = _route_path(request.scope)
    if path is None:
        path = getattr(request.url, "path", None)
    if not isinstance(path, str):
        path = str(request.scope.get("path", ""))
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

    Usage:
        app.middleware("http")(retry_middleware(policy))

    Provide either `policy` (shared) or `policy_provider` (per-request).
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
]
