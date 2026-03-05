"""HTTPX integration helpers.

This module stays dependency-light by using protocols instead of importing
httpx directly. It provides sync/async wrappers that route client requests
through a redress policy, plus small HTTP-focused helpers.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any, Generic, Protocol, TypeVar
from urllib.parse import urlsplit

from ..classify import Classification
from ..errors import ErrorClass

ResponseT = TypeVar("ResponseT")
ResponseT_co = TypeVar("ResponseT_co", covariant=True)
OptionT = TypeVar("OptionT")


class ResponseLike(Protocol):
    status_code: int
    headers: object


class SyncClientLike(Protocol[ResponseT_co]):
    def request(self, method: str, url: object, **kwargs: Any) -> ResponseT_co: ...


class AsyncClientLike(Protocol[ResponseT_co]):
    async def request(self, method: str, url: object, **kwargs: Any) -> ResponseT_co: ...


class SyncPolicyLike(Protocol[ResponseT]):
    def call(self, func: Callable[[], ResponseT], **kwargs: Any) -> ResponseT: ...


class AsyncPolicyLike(Protocol[ResponseT]):
    async def call(
        self, func: Callable[[], Awaitable[ResponseT]], **kwargs: Any
    ) -> ResponseT: ...


OperationBuilder = Callable[[str, object], str | None]
RequestPredicate = Callable[[str, object], bool]
CallKwargsProvider = Callable[[str, object], Mapping[str, Any]]

IDEMPOTENT_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PUT"})


def is_idempotent_method(method: str) -> bool:
    """
    Return True when `method` is idempotent under HTTP semantics.
    """
    return method.upper() in IDEMPOTENT_METHODS


def _url_path(url: object) -> str:
    path = getattr(url, "path", None)
    if isinstance(path, str) and path:
        return path

    raw = url if isinstance(url, str) else str(url)
    if not raw:
        return "/"

    parsed = urlsplit(raw)
    path = parsed.path
    if parsed.scheme or parsed.netloc:
        return path or "/"
    if path:
        return path if path.startswith("/") else f"/{path}"
    if raw.startswith("/"):
        return raw
    return f"/{raw}"


def default_operation(method: str, url: object) -> str:
    """
    Build an operation as "{METHOD} {path}".

    Path omits query strings to reduce cardinality in metrics/logs.
    """
    return f"{method.upper()} {_url_path(url)}"


def _lookup_header(headers: object, name: str) -> str | None:
    if headers is None:
        return None
    if isinstance(headers, Mapping):
        value = headers.get(name)
        if value is None:
            value = headers.get(name.lower())
        if value is not None:
            return str(value)
        for key, val in headers.items():
            if str(key).lower() == name.lower():
                return str(val)
        return None

    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is None:
            value = getter(name.lower())
        if value is not None:
            return str(value)
    return None


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        seconds = int(raw)
        return max(0.0, float(seconds))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        delta = (parsed - datetime.now(UTC)).total_seconds()
        return max(0.0, delta)


def default_result_classifier(response: ResponseLike) -> ErrorClass | Classification | None:
    """
    Classify an HTTP response for retry decisions.

    Returns None for non-retryable statuses so callers can keep handling those
    responses directly.
    """
    status = response.status_code

    if status == 429:
        retry_after = _parse_retry_after(_lookup_header(response.headers, "Retry-After"))
        if retry_after is not None:
            return Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=retry_after)
        return ErrorClass.RATE_LIMIT
    if status == 408:
        return ErrorClass.TRANSIENT
    if status == 409:
        return ErrorClass.CONCURRENCY
    if 500 <= status < 600:
        return ErrorClass.SERVER_ERROR
    return None


def _resolve_operation(
    operation: str | OperationBuilder | None,
    method: str,
    url: object,
) -> str | None:
    if operation is None:
        return default_operation(method, url)
    if callable(operation):
        return operation(method, url)
    return operation


def _resolve_call_kwargs(
    call_kwargs: Mapping[str, Any] | CallKwargsProvider | None,
    method: str,
    url: object,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if call_kwargs is None:
        return kwargs
    if callable(call_kwargs):
        kwargs.update(call_kwargs(method, url))
    else:
        kwargs.update(call_kwargs)
    return kwargs


def _choose_option(default: OptionT, override: OptionT | None) -> OptionT:
    if override is None:
        return default
    return override


def request_with_retry(
    client: SyncClientLike[ResponseT],
    policy: SyncPolicyLike[ResponseT],
    method: str,
    url: object,
    *,
    operation: str | OperationBuilder | None = None,
    skip_if: RequestPredicate | None = None,
    call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
    **request_kwargs: Any,
) -> ResponseT:
    """
    Execute `client.request(...)` wrapped by a sync policy call.
    """
    normalized_method = method.upper()
    if skip_if is not None and skip_if(normalized_method, url):
        return client.request(method, url, **request_kwargs)

    kwargs = _resolve_call_kwargs(call_kwargs, normalized_method, url)
    if "operation" not in kwargs:
        operation_value = _resolve_operation(operation, normalized_method, url)
        if operation_value is not None:
            kwargs["operation"] = operation_value

    def _call() -> ResponseT:
        return client.request(method, url, **request_kwargs)

    return policy.call(_call, **kwargs)


async def arequest_with_retry(
    client: AsyncClientLike[ResponseT],
    policy: AsyncPolicyLike[ResponseT],
    method: str,
    url: object,
    *,
    operation: str | OperationBuilder | None = None,
    skip_if: RequestPredicate | None = None,
    call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
    **request_kwargs: Any,
) -> ResponseT:
    """
    Execute `client.request(...)` wrapped by an async policy call.
    """
    normalized_method = method.upper()
    if skip_if is not None and skip_if(normalized_method, url):
        return await client.request(method, url, **request_kwargs)

    kwargs = _resolve_call_kwargs(call_kwargs, normalized_method, url)
    if "operation" not in kwargs:
        operation_value = _resolve_operation(operation, normalized_method, url)
        if operation_value is not None:
            kwargs["operation"] = operation_value

    async def _call() -> ResponseT:
        return await client.request(method, url, **request_kwargs)

    return await policy.call(_call, **kwargs)


class RetryingHttpxClient(Generic[ResponseT]):
    """
    Thin wrapper that applies a sync policy to every request call.
    """

    def __init__(
        self,
        client: SyncClientLike[ResponseT],
        policy: SyncPolicyLike[ResponseT],
        *,
        operation: str | OperationBuilder | None = None,
        skip_if: RequestPredicate | None = None,
        call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
    ) -> None:
        self.client = client
        self.policy = policy
        self.operation = operation
        self.skip_if = skip_if
        self.call_kwargs = call_kwargs

    def request(
        self,
        method: str,
        url: object,
        *,
        operation: str | OperationBuilder | None = None,
        skip_if: RequestPredicate | None = None,
        call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
        **request_kwargs: Any,
    ) -> ResponseT:
        return request_with_retry(
            client=self.client,
            policy=self.policy,
            method=method,
            url=url,
            operation=_choose_option(self.operation, operation),
            skip_if=_choose_option(self.skip_if, skip_if),
            call_kwargs=_choose_option(self.call_kwargs, call_kwargs),
            **request_kwargs,
        )

    def get(self, url: object, **kwargs: Any) -> ResponseT:
        return self.request("GET", url, **kwargs)

    def post(self, url: object, **kwargs: Any) -> ResponseT:
        return self.request("POST", url, **kwargs)

    def put(self, url: object, **kwargs: Any) -> ResponseT:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: object, **kwargs: Any) -> ResponseT:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: object, **kwargs: Any) -> ResponseT:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: object, **kwargs: Any) -> ResponseT:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: object, **kwargs: Any) -> ResponseT:
        return self.request("OPTIONS", url, **kwargs)

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "RetryingHttpxClient[ResponseT]":
        enter = getattr(self.client, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        exit_method = getattr(self.client, "__exit__", None)
        if callable(exit_method):
            return bool(exit_method(exc_type, exc, tb))
        self.close()
        return False


class AsyncRetryingHttpxClient(Generic[ResponseT]):
    """
    Thin wrapper that applies an async policy to every request call.
    """

    def __init__(
        self,
        client: AsyncClientLike[ResponseT],
        policy: AsyncPolicyLike[ResponseT],
        *,
        operation: str | OperationBuilder | None = None,
        skip_if: RequestPredicate | None = None,
        call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
    ) -> None:
        self.client = client
        self.policy = policy
        self.operation = operation
        self.skip_if = skip_if
        self.call_kwargs = call_kwargs

    async def request(
        self,
        method: str,
        url: object,
        *,
        operation: str | OperationBuilder | None = None,
        skip_if: RequestPredicate | None = None,
        call_kwargs: Mapping[str, Any] | CallKwargsProvider | None = None,
        **request_kwargs: Any,
    ) -> ResponseT:
        return await arequest_with_retry(
            client=self.client,
            policy=self.policy,
            method=method,
            url=url,
            operation=_choose_option(self.operation, operation),
            skip_if=_choose_option(self.skip_if, skip_if),
            call_kwargs=_choose_option(self.call_kwargs, call_kwargs),
            **request_kwargs,
        )

    async def get(self, url: object, **kwargs: Any) -> ResponseT:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: object, **kwargs: Any) -> ResponseT:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: object, **kwargs: Any) -> ResponseT:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: object, **kwargs: Any) -> ResponseT:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: object, **kwargs: Any) -> ResponseT:
        return await self.request("DELETE", url, **kwargs)

    async def head(self, url: object, **kwargs: Any) -> ResponseT:
        return await self.request("HEAD", url, **kwargs)

    async def options(self, url: object, **kwargs: Any) -> ResponseT:
        return await self.request("OPTIONS", url, **kwargs)

    async def aclose(self) -> None:
        close = getattr(self.client, "aclose", None)
        if callable(close):
            await close()

    async def __aenter__(self) -> "AsyncRetryingHttpxClient[ResponseT]":
        enter = getattr(self.client, "__aenter__", None)
        if callable(enter):
            await enter()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        exit_method = getattr(self.client, "__aexit__", None)
        if callable(exit_method):
            return bool(await exit_method(exc_type, exc, tb))
        await self.aclose()
        return False


__all__ = [
    "AsyncRetryingHttpxClient",
    "IDEMPOTENT_METHODS",
    "AsyncClientLike",
    "AsyncPolicyLike",
    "CallKwargsProvider",
    "OperationBuilder",
    "RequestPredicate",
    "ResponseLike",
    "RetryingHttpxClient",
    "SyncClientLike",
    "SyncPolicyLike",
    "arequest_with_retry",
    "default_operation",
    "default_result_classifier",
    "is_idempotent_method",
    "request_with_retry",
]
