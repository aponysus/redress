"""gRPC client interceptor helpers.

This module is dependency-light and imports `grpc` lazily. It provides
unary-unary client interceptor factories for sync `grpc` and async `grpc.aio`
that route calls through a redress policy.
"""

import importlib
import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypeVar, cast

CallT = TypeVar("CallT")
RequestT = TypeVar("RequestT")


class ClientCallDetailsLike(Protocol):
    method: object


class SyncPolicyLike(Protocol[CallT]):
    def call(self, func: Callable[[], CallT], **kwargs: Any) -> CallT: ...


class AsyncPolicyLike(Protocol[CallT]):
    async def call(self, func: Callable[[], Awaitable[CallT]], **kwargs: Any) -> CallT: ...


SyncPolicyProvider = Callable[[ClientCallDetailsLike, object], SyncPolicyLike[Any]]
AsyncPolicyProvider = Callable[[ClientCallDetailsLike, object], AsyncPolicyLike[Any]]
OperationBuilder = Callable[[ClientCallDetailsLike], str | None]
SkipPredicate = Callable[[ClientCallDetailsLike, object], bool]
CallKwargsProvider = Callable[[ClientCallDetailsLike, object], Mapping[str, Any]]


def _normalize_method_path(method: object) -> str:
    if isinstance(method, bytes):
        raw = method.decode("utf-8", "replace")
    elif isinstance(method, str):
        raw = method
    else:
        raw = str(method)

    raw = raw.strip()
    if not raw:
        return "/"
    if not raw.startswith("/"):
        return f"/{raw}"
    return raw


def default_operation(client_call_details: ClientCallDetailsLike) -> str:
    """
    Build a default operation tag from the RPC method path.
    """
    return f"grpc {_normalize_method_path(client_call_details.method)}"


def rpc_service_name(client_call_details: ClientCallDetailsLike) -> str | None:
    """
    Return the fully qualified gRPC service name from method path.
    """
    path = _normalize_method_path(client_call_details.method).strip("/")
    if not path:
        return None
    parts = path.split("/")
    if len(parts) < 2:
        return None
    service = "/".join(parts[:-1]).strip()
    return service or None


def rpc_method_name(client_call_details: ClientCallDetailsLike) -> str | None:
    """
    Return the RPC method name from method path.
    """
    path = _normalize_method_path(client_call_details.method).strip("/")
    if not path:
        return None
    parts = path.split("/")
    if len(parts) < 2:
        return None
    method = parts[-1].strip()
    return method or None


def _resolve_call_kwargs(
    call_kwargs: Mapping[str, Any] | CallKwargsProvider | None,
    client_call_details: ClientCallDetailsLike,
    request: object,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if call_kwargs is None:
        return kwargs
    if callable(call_kwargs):
        kwargs.update(call_kwargs(client_call_details, request))
    else:
        kwargs.update(call_kwargs)
    return kwargs


def _resolve_operation(
    operation: str | OperationBuilder | None,
    client_call_details: ClientCallDetailsLike,
) -> str | None:
    if operation is None:
        return default_operation(client_call_details)
    if callable(operation):
        return operation(client_call_details)
    return operation


def _is_done_call(call: object) -> bool:
    done = getattr(call, "done", None)
    if not callable(done):
        return True
    try:
        return bool(done())
    except Exception:
        return False


def unary_unary_client_interceptor(
    policy: SyncPolicyLike[Any] | None = None,
    *,
    policy_provider: SyncPolicyProvider | None = None,
    operation: str | OperationBuilder | None = None,
    skip_if: SkipPredicate | None = None,
    call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
) -> object:
    """
    Build a sync unary-unary client interceptor that wraps calls in a policy.

    Notes:
      - Retries are applied reliably for blocking unary calls (`stub.Method(...)`).
      - For `.future(...)`, calls are not eagerly awaited; retries on terminal
        RPC status are therefore not guaranteed by this interceptor.
    """
    if (policy is None) == (policy_provider is None):
        raise ValueError("Provide exactly one of policy or policy_provider.")

    try:
        grpc_mod = importlib.import_module("grpc")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("grpcio is required for redress.contrib.grpc") from exc

    def _intercept_unary_unary(
        self: object,
        continuation: Callable[[ClientCallDetailsLike, RequestT], CallT],
        client_call_details: ClientCallDetailsLike,
        request: RequestT,
    ) -> CallT:
        if skip_if is not None and skip_if(client_call_details, request):
            return continuation(client_call_details, request)

        policy_obj = (
            policy_provider(client_call_details, request) if policy_provider is not None else policy
        )
        if policy_obj is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Retry policy missing.")

        kwargs = _resolve_call_kwargs(call_kwargs, client_call_details, request)
        if "operation" not in kwargs:
            operation_value = _resolve_operation(operation, client_call_details)
            if operation_value is not None:
                kwargs["operation"] = operation_value

        def _call() -> CallT:
            call = continuation(client_call_details, request)
            # Unary blocking path returns completed call outcomes; checking
            # result() here surfaces RpcError for policy classification.
            if _is_done_call(call):
                result = getattr(call, "result", None)
                if callable(result):
                    result()
            return call

        return cast(CallT, policy_obj.call(_call, **kwargs))

    interceptor_cls = type(
        "_UnaryUnaryRetryInterceptor",
        (cast(Any, grpc_mod.UnaryUnaryClientInterceptor),),
        {"intercept_unary_unary": _intercept_unary_unary},
    )
    return interceptor_cls()


def aio_unary_unary_client_interceptor(
    policy: AsyncPolicyLike[Any] | None = None,
    *,
    policy_provider: AsyncPolicyProvider | None = None,
    operation: str | OperationBuilder | None = None,
    skip_if: SkipPredicate | None = None,
    call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
) -> object:
    """
    Build an async unary-unary client interceptor that wraps calls in a policy.
    """
    if (policy is None) == (policy_provider is None):
        raise ValueError("Provide exactly one of policy or policy_provider.")

    try:
        aio_mod = importlib.import_module("grpc.aio")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("grpcio is required for redress.contrib.grpc") from exc

    async def _intercept_unary_unary(
        self: object,
        continuation: Callable[[ClientCallDetailsLike, RequestT], Awaitable[CallT]],
        client_call_details: ClientCallDetailsLike,
        request: RequestT,
    ) -> CallT:
        if skip_if is not None and skip_if(client_call_details, request):
            return await continuation(client_call_details, request)

        policy_obj = (
            policy_provider(client_call_details, request) if policy_provider is not None else policy
        )
        if policy_obj is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Retry policy missing.")

        kwargs = _resolve_call_kwargs(call_kwargs, client_call_details, request)
        if "operation" not in kwargs:
            operation_value = _resolve_operation(operation, client_call_details)
            if operation_value is not None:
                kwargs["operation"] = operation_value

        async def _call() -> CallT:
            call_or_response = await continuation(client_call_details, request)
            if inspect.isawaitable(call_or_response):
                await call_or_response
            return call_or_response

        return cast(CallT, await policy_obj.call(_call, **kwargs))

    interceptor_cls = type(
        "_AioUnaryUnaryRetryInterceptor",
        (cast(Any, aio_mod.UnaryUnaryClientInterceptor),),
        {"intercept_unary_unary": _intercept_unary_unary},
    )
    return interceptor_cls()


__all__ = [
    "AsyncPolicyLike",
    "AsyncPolicyProvider",
    "CallKwargsProvider",
    "ClientCallDetailsLike",
    "OperationBuilder",
    "SkipPredicate",
    "SyncPolicyLike",
    "SyncPolicyProvider",
    "aio_unary_unary_client_interceptor",
    "default_operation",
    "rpc_method_name",
    "rpc_service_name",
    "unary_unary_client_interceptor",
]
