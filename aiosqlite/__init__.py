"""Minimal local fallback for aiosqlite.

This implementation is synchronous under the hood but exposes the async
surface that SQLAlchemy's sqlite+aiosqlite dialect expects.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

DatabaseError = sqlite3.DatabaseError
Error = sqlite3.Error
IntegrityError = sqlite3.IntegrityError
NotSupportedError = sqlite3.NotSupportedError
OperationalError = sqlite3.OperationalError
ProgrammingError = sqlite3.ProgrammingError
sqlite_version = sqlite3.sqlite_version
sqlite_version_info = sqlite3.sqlite_version_info


class Cursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    async def execute(self, operation, parameters=None):
        if parameters is None:
            self._cursor.execute(operation)
        else:
            self._cursor.execute(operation, parameters)
        return self

    async def executemany(self, operation, seq_of_parameters: Iterable):
        self._cursor.executemany(operation, seq_of_parameters)
        return self

    async def fetchall(self):
        return self._cursor.fetchall()

    async def fetchone(self):
        return self._cursor.fetchone()

    async def fetchmany(self, size=None):
        return self._cursor.fetchmany(size)

    async def close(self):
        self._cursor.close()


class Connection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.daemon = True

    def __await__(self):
        async def _return_self():
            return self

        return _return_self().__await__()

    async def cursor(self):
        return Cursor(self._conn.cursor())

    async def commit(self):
        self._conn.commit()

    async def rollback(self):
        self._conn.rollback()

    async def close(self):
        self._conn.close()

    async def create_function(self, *args, **kwargs):
        self._conn.create_function(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._conn, item)


PARSE_COLNAMES = sqlite3.PARSE_COLNAMES
PARSE_DECLTYPES = sqlite3.PARSE_DECLTYPES
Binary = sqlite3.Binary


def connect(database, *args, **kwargs):
    kwargs.pop("loop", None)
    kwargs["check_same_thread"] = False
    conn = sqlite3.connect(database, *args, **kwargs)
    return Connection(conn)
