from .errors import (
    ConcurrencyError,
    ErrorClass,
    PermanentError,
    RateLimitError,
    ServerError,
)


def default_classifier(err: BaseException) -> ErrorClass:
    """
    Map an exception into a coarse ErrorClass.

    Classification order (first match wins):

      1. Explicit redress error types:
         - PermanentError     -> PERMANENT
         - RateLimitError     -> RATE_LIMIT
         - ConcurrencyError   -> CONCURRENCY
         - ServerError        -> SERVER_ERROR

      2. Numeric codes on the exception object:
         We look at `err.status` or `err.code`, which covers typical HTTP
         clients (`status=429`) and some SDKs.

         - 401                -> AUTH
         - 403                -> PERMISSION
         - 400, 404, 422      -> PERMANENT
         - 409                -> CONCURRENCY
         - 429                -> RATE_LIMIT
         - 5xx                -> SERVER_ERROR

      3. Name-based heuristics:
         - Exception class name contains auth/unauthoriz/credential -> AUTH
         - Exception class name contains forbid/permission -> PERMISSION
         - Exception class name contains "timeout" or "connection" -> TRANSIENT

      4. Fallback:
         - UNKNOWN
    """

    if isinstance(err, PermanentError):
        return ErrorClass.PERMANENT
    if isinstance(err, RateLimitError):
        return ErrorClass.RATE_LIMIT
    if isinstance(err, ConcurrencyError):
        return ErrorClass.CONCURRENCY
    if isinstance(err, ServerError):
        return ErrorClass.SERVER_ERROR

    code = getattr(err, "status", None) or getattr(err, "code", None)

    if isinstance(code, int):
        if code == 401:
            return ErrorClass.AUTH
        if code == 403:
            return ErrorClass.PERMISSION
        if code in (400, 404, 422):
            return ErrorClass.PERMANENT
        if code == 409:
            return ErrorClass.CONCURRENCY
        if code == 408:
            return ErrorClass.TRANSIENT
        if code == 429:
            return ErrorClass.RATE_LIMIT
        if 500 <= code < 600:
            return ErrorClass.SERVER_ERROR

    name = type(err).__name__.lower()
    if "auth" in name or "unauthoriz" in name or "credential" in name:
        return ErrorClass.AUTH
    if "forbid" in name or "permission" in name:
        return ErrorClass.PERMISSION
    if "timeout" in name or "connection" in name:
        return ErrorClass.TRANSIENT

    return ErrorClass.UNKNOWN
