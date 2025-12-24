"""
Example: retrying pyodbc queries with a SQLSTATE-based classifier.

This script shows how to:
  * Build a RetryPolicy that understands pyodbc SQLSTATE codes
  * Connect to a database with pyodbc
  * Fetch rows in batches with retries

Setup:
  pip install pyodbc redress
  export PYODBC_CONN_STR="DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=mydb;UID=user;PWD=pass"

Note: adjust the connection string and query for your environment. The classifier
is intentionally minimal. Adapt codes to your driver/server behavior.
"""

import os
from collections.abc import Iterable, Iterator, Sequence

import pyodbc

from docs.snippets.pyodbc_classifier import pyodbc_classifier
from redress import RetryPolicy
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter


def fetch_rows_in_batches(
    *,
    conn: pyodbc.Connection,
    table: str,
    batch_size: int = 500,
    order_by: str = "id",
) -> Iterator[Sequence[pyodbc.Row]]:
    """
    Stream rows from `table` in batches, ordered deterministically.
    """
    offset = 0
    cursor = conn.cursor()

    while True:
        query = f"SELECT * FROM {table} ORDER BY {order_by} OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
        cursor.execute(query, (offset, batch_size))
        rows = cursor.fetchall()
        if not rows:
            break
        yield rows
        offset += batch_size


def main() -> None:
    conn_str = os.getenv("PYODBC_CONN_STR")
    if not conn_str:
        raise SystemExit(
            "Set PYODBC_CONN_STR, e.g., "
            "'DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=mydb;UID=user;PWD=pass'"
        )

    policy = RetryPolicy(
        classifier=pyodbc_classifier,
        # Use faster retries for transient/timeout classes, and longer for concurrency
        strategy=decorrelated_jitter(base_s=0.1, max_s=2.0),
        strategies={
            ErrorClass.CONCURRENCY: decorrelated_jitter(base_s=0.5, max_s=10.0),
        },
        deadline_s=30.0,
        max_attempts=6,
    )

    def load_all() -> Iterable[Sequence[pyodbc.Row]]:
        with pyodbc.connect(conn_str, autocommit=True) as conn:
            yield from fetch_rows_in_batches(
                conn=conn,
                table="some_table",
                batch_size=500,
                order_by="id",  # ensure this is indexed/deterministic
            )

    # Execute under retry; any transient/concurrency errors will be retried per classifier/strategy.
    for batch in policy.call(lambda: list(load_all()), operation="pyodbc_batch_fetch"):
        print(f"Fetched {len(batch)} rows")


if __name__ == "__main__":
    main()
