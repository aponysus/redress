# tests/test_contrib_pyodbc.py

from redress.contrib.pyodbc import pyodbc_classifier
from redress.errors import ErrorClass


def test_pyodbc_classifier_sqlstate_attr() -> None:
    class PyodbcError(Exception):
        def __init__(self, sqlstate: str) -> None:
            self.sqlstate = sqlstate

    assert pyodbc_classifier(PyodbcError("40001")) is ErrorClass.CONCURRENCY
    assert pyodbc_classifier(PyodbcError("40P01")) is ErrorClass.CONCURRENCY
    assert pyodbc_classifier(PyodbcError("28000")) is ErrorClass.AUTH
    assert pyodbc_classifier(PyodbcError("HYT00")) is ErrorClass.TRANSIENT
    assert pyodbc_classifier(PyodbcError("HYT01")) is ErrorClass.TRANSIENT
    assert pyodbc_classifier(PyodbcError("08S01")) is ErrorClass.TRANSIENT
    assert pyodbc_classifier(PyodbcError("08006")) is ErrorClass.TRANSIENT
    assert pyodbc_classifier(PyodbcError("42000")) is ErrorClass.PERMANENT
    assert pyodbc_classifier(PyodbcError("42P01")) is ErrorClass.PERMANENT


def test_pyodbc_classifier_extracts_sqlstate_from_args() -> None:
    class PyodbcError(Exception):
        pass

    timeout = PyodbcError("driver timeout")
    timeout.args = (500, "[HYT00] [unixODBC] timeout expired")  # type: ignore[assignment]
    assert pyodbc_classifier(timeout) is ErrorClass.TRANSIENT

    deadlock = PyodbcError("deadlock")
    deadlock.args = ("[40P01] deadlock detected",)  # type: ignore[assignment]
    assert pyodbc_classifier(deadlock) is ErrorClass.CONCURRENCY

    auth = PyodbcError("auth")
    auth.args = ("[28000] login failed",)  # type: ignore[assignment]
    assert pyodbc_classifier(auth) is ErrorClass.AUTH

    permanent = PyodbcError("missing table")
    permanent.args = ("[42P01] relation does not exist",)  # type: ignore[assignment]
    assert pyodbc_classifier(permanent) is ErrorClass.PERMANENT


def test_pyodbc_classifier_unknown_without_sqlstate() -> None:
    class PyodbcError(Exception):
        pass

    err = PyodbcError("misc")
    err.args = (123, object(), "no sqlstate here")  # type: ignore[assignment]
    assert pyodbc_classifier(err) is ErrorClass.UNKNOWN
