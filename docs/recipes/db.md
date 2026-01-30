# DB classifiers (SQLSTATE)

SQLSTATE-based classifiers are a reliable way to handle database errors across
pyodbc, asyncpg, psycopg, and other DBAPI-style drivers.

## Basic SQLSTATE retry policy

```python
from redress import Policy, Retry
from redress.extras import sqlstate_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=sqlstate_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        max_attempts=5,
        deadline_s=10.0,
    )
)


def run_query(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM widgets")
        return cur.fetchall()

rows = policy.call(lambda: run_query(conn), operation="db_query")
```

## Per-class strategies for deadlocks/timeouts

```python
from redress import Policy, Retry
from redress.errors import ErrorClass
from redress.extras import sqlstate_classifier
from redress.strategies import decorrelated_jitter, equal_jitter

policy = Policy(
    retry=Retry(
        classifier=sqlstate_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        strategies={
            ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=0.5),
            ErrorClass.TRANSIENT: equal_jitter(max_s=1.0),
        },
        max_attempts=6,
        deadline_s=12.0,
    )
)
```

## pyodbc helper

If you use pyodbc, you can use `pyodbc_classifier` (also in `redress.extras`).
It extracts SQLSTATE codes from driver errors with no dependency on pyodbc itself.

```python
from redress import Policy, Retry
from redress.extras import pyodbc_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=pyodbc_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
    )
)
```
