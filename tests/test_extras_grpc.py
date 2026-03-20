import redress.extras.grpc as grpc_extra
from redress.classify import default_classifier
from redress.errors import ErrorClass


class _StatusCode:
    RESOURCE_EXHAUSTED = object()
    UNAVAILABLE = object()
    DEADLINE_EXCEEDED = object()
    UNAUTHENTICATED = object()
    PERMISSION_DENIED = object()
    INVALID_ARGUMENT = object()
    FAILED_PRECONDITION = object()
    OUT_OF_RANGE = object()
    NOT_FOUND = object()
    INTERNAL = object()
    DATA_LOSS = object()
    CANCELLED = object()
    UNKNOWN = object()


class _RpcError(Exception):
    def __init__(self, status: object | None, *, callable_code: bool = True) -> None:
        self._status = status
        if not callable_code:
            self.code = status

    def code(self) -> object | None:
        return self._status


class _AioRpcError(Exception):
    def __init__(self, status: object | None, *, callable_code: bool = True) -> None:
        self._status = status
        if not callable_code:
            self.code = status

    def code(self) -> object | None:
        return self._status


class _GrpcModule:
    RpcError = _RpcError
    StatusCode = _StatusCode


class _GrpcAioModule:
    AioRpcError = _AioRpcError


def test_grpc_classifier_falls_back_when_grpc_missing(monkeypatch) -> None:
    def fake_import(name: str):
        raise ImportError(name)

    monkeypatch.setattr(grpc_extra.importlib, "import_module", fake_import)

    class MiscError(Exception):
        pass

    err = MiscError("boom")
    assert grpc_extra.grpc_classifier(err) is default_classifier(err)


def test_grpc_classifier_sync_rpc_error_status_mappings(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "grpc":
            return _GrpcModule
        if name == "grpc.aio":
            raise ImportError(name)
        raise AssertionError(name)

    monkeypatch.setattr(grpc_extra.importlib, "import_module", fake_import)

    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.RESOURCE_EXHAUSTED)) is ErrorClass.RATE_LIMIT
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.UNAVAILABLE)) is ErrorClass.TRANSIENT
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.DEADLINE_EXCEEDED)) is ErrorClass.TRANSIENT
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.UNAUTHENTICATED)) is ErrorClass.AUTH
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.PERMISSION_DENIED)) is ErrorClass.PERMISSION
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.INVALID_ARGUMENT)) is ErrorClass.PERMANENT
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.FAILED_PRECONDITION)) is ErrorClass.PERMANENT
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.OUT_OF_RANGE)) is ErrorClass.PERMANENT
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.NOT_FOUND)) is ErrorClass.PERMANENT
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.INTERNAL)) is ErrorClass.SERVER_ERROR
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.DATA_LOSS)) is ErrorClass.SERVER_ERROR
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.CANCELLED)) is ErrorClass.PERMANENT
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.UNKNOWN)) is ErrorClass.UNKNOWN
    assert grpc_extra.grpc_classifier(_RpcError(object())) is ErrorClass.UNKNOWN


def test_grpc_classifier_async_aio_rpc_error_path(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "grpc":
            return _GrpcModule
        if name == "grpc.aio":
            return _GrpcAioModule
        raise AssertionError(name)

    monkeypatch.setattr(grpc_extra.importlib, "import_module", fake_import)

    assert grpc_extra.grpc_classifier(_AioRpcError(_StatusCode.UNAVAILABLE)) is ErrorClass.TRANSIENT


def test_grpc_classifier_returns_unknown_when_code_missing_or_noncallable(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "grpc":
            return _GrpcModule
        if name == "grpc.aio":
            return _GrpcAioModule
        raise AssertionError(name)

    monkeypatch.setattr(grpc_extra.importlib, "import_module", fake_import)

    assert grpc_extra.grpc_classifier(_RpcError(None)) is ErrorClass.UNKNOWN
    assert grpc_extra.grpc_classifier(_RpcError(_StatusCode.UNAVAILABLE, callable_code=False)) is ErrorClass.UNKNOWN
    assert grpc_extra.grpc_classifier(_AioRpcError(_StatusCode.UNAVAILABLE, callable_code=False)) is ErrorClass.UNKNOWN


def test_map_grpc_status_handles_missing_status_code_object() -> None:
    class _MissingStatusGrpc:
        StatusCode = None

    assert grpc_extra._map_grpc_status(_MissingStatusGrpc, object()) is ErrorClass.UNKNOWN

