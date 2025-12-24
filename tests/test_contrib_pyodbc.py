# tests/test_contrib_pyodbc.py

from redress.contrib.pyodbc import pyodbc_classifier
from redress.errors import ErrorClass


def test_pyodbc_classifier_sqlstate_attr() -> None:
    class PyodbcError(Exception):
        def __init__(self, sqlstate: str) -> None:
            self.sqlstate = sqlstate

    assert pyodbc_classifier(PyodbcError("40001")) is ErrorClass.CONCURRENCY
    assert pyodbc_classifier(PyodbcError("28000")) is ErrorClass.AUTH
    assert pyodbc_classifier(PyodbcError("HYT00")) is ErrorClass.TRANSIENT
