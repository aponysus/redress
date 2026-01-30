"""Optional gRPC classifier."""

import importlib

from ..classify import default_classifier
from ..errors import ErrorClass


def grpc_classifier(exc: BaseException) -> ErrorClass:
    """
    Classify gRPC exceptions into ErrorClass.

    This helper is optional and degrades gracefully when grpcio is unavailable.
    """
    try:
        grpc_mod = importlib.import_module("grpc")
    except Exception:
        return default_classifier(exc)

    rpc_error = getattr(grpc_mod, "RpcError", None)
    aio_rpc_error = None
    try:
        grpc_aio = importlib.import_module("grpc.aio")
        aio_rpc_error = getattr(grpc_aio, "AioRpcError", None)
    except Exception:
        aio_rpc_error = None

    if rpc_error is not None and isinstance(rpc_error, type) and isinstance(exc, rpc_error):
        code = getattr(exc, "code", None)
        status = code() if callable(code) else None
        return _map_grpc_status(grpc_mod, status)

    if aio_rpc_error is not None and isinstance(aio_rpc_error, type) and isinstance(exc, aio_rpc_error):
        code = getattr(exc, "code", None)
        status = code() if callable(code) else None
        return _map_grpc_status(grpc_mod, status)

    return default_classifier(exc)


def _map_grpc_status(grpc_mod: object, status: object) -> ErrorClass:
    status_code = getattr(grpc_mod, "StatusCode", None)
    if status_code is None or status is None:
        return ErrorClass.UNKNOWN

    mapping = {
        getattr(status_code, "RESOURCE_EXHAUSTED", None): ErrorClass.RATE_LIMIT,
        getattr(status_code, "UNAVAILABLE", None): ErrorClass.TRANSIENT,
        getattr(status_code, "DEADLINE_EXCEEDED", None): ErrorClass.TRANSIENT,
        getattr(status_code, "UNAUTHENTICATED", None): ErrorClass.AUTH,
        getattr(status_code, "PERMISSION_DENIED", None): ErrorClass.PERMISSION,
        getattr(status_code, "INVALID_ARGUMENT", None): ErrorClass.PERMANENT,
        getattr(status_code, "FAILED_PRECONDITION", None): ErrorClass.PERMANENT,
        getattr(status_code, "OUT_OF_RANGE", None): ErrorClass.PERMANENT,
        getattr(status_code, "NOT_FOUND", None): ErrorClass.PERMANENT,
        getattr(status_code, "INTERNAL", None): ErrorClass.SERVER_ERROR,
        getattr(status_code, "DATA_LOSS", None): ErrorClass.SERVER_ERROR,
        getattr(status_code, "CANCELLED", None): ErrorClass.PERMANENT,
    }
    mapped = mapping.get(status)
    if mapped is not None:
        return mapped

    if status == getattr(status_code, "UNKNOWN", None):
        return ErrorClass.UNKNOWN

    return ErrorClass.UNKNOWN
