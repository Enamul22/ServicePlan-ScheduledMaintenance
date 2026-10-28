"""SQLite locally; TLS PostgreSQL for durable hosted state. No silent backend fallback."""

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import pandas as pd
import psycopg
from psycopg import sql


class StorageError(ValueError):
    """Safe-to-display storage failure; never includes the connection string."""


def validate_schema(schema):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema) or schema.startswith("pg_"):
        raise ValueError("Invalid database schema name")
    return schema


def validate_url(url):
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("postgresql", "postgres")
            or not parsed.hostname
            or not parsed.path.strip("/")
        ):
            raise ValueError
        mode = parse_qs(parsed.query).get("sslmode", ["require"])[0]
        local_test = parsed.hostname in ("localhost", "127.0.0.1", "::1") and mode == "disable"
        if mode not in ("require", "verify-ca", "verify-full") and not local_test:
            raise ValueError
        return mode
    except (ValueError, TypeError, AttributeError):
        raise StorageError(
            "Configure a valid PostgreSQL URL with TLS (sslmode=require or stronger)."
        ) from None


class Record(dict):
    """The service's existing SQLite-style named and positional row access."""

    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def record_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Record(zip(names, values))


class SQLiteStore:
    backend = "sqlite"

    def __init__(self, path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            str(path), timeout=30, check_same_thread=False, isolation_level=None
        )
        self.connection.row_factory = sqlite3.Row
        self.execute("pragma foreign_keys=on")
        self.execute("pragma journal_mode=wal")
        self.execute("pragma busy_timeout=30000")

    def execute(self, query, params=()):
        return self.connection.execute(query, params)

    def executemany(self, query, rows):
        return self.connection.executemany(query, rows)

    def executescript(self, script):
        return self.connection.executescript(script)

    def columns(self, table):
        # Table identifiers are internal schema constants, never request input.
        return [r[1] for r in self.execute(f'pragma table_info("{validate_schema(table)}")')]

    def tables(self):
        return {r[0] for r in self.execute("select name from sqlite_master where type='table'")}

    @contextmanager
    def transaction(self):
        self.execute("begin immediate")
        try:
            yield
            self.execute("commit")
        except BaseException:
            self.execute("rollback")
            raise

    def frame(self, query, params=()):
        cursor = self.execute(query, params)
        return pd.DataFrame.from_records(
            [dict(r) for r in cursor.fetchall()], columns=[c[0] for c in cursor.description]
        )

    def close(self):
        self.connection.close()


class PostgresStore:
    backend = "postgresql"

    def __init__(self, url, schema="serviceplan"):
        self._url = url
        self._sslmode = validate_url(url)
        if not re.fullmatch(r"/serviceplan(?:_[a-z0-9_]+)?", urlsplit(url).path):
            raise StorageError("Use a separate ServicePlan database, never the FleetCare database")
        self.schema = validate_schema(schema)
        if not (schema == "serviceplan" or schema.startswith("serviceplan_")):
            raise StorageError("ServicePlan must use its own serviceplan schema namespace")
        self.connection = None
        self._in_transaction = False
        self._lock = int.from_bytes(hashlib.sha256(schema.encode()).digest()[:8], "big", signed=True)

    def _connect(self):
        if self.connection is None or self.connection.closed:
            try:
                self.connection = psycopg.connect(
                    self._url,
                    sslmode=self._sslmode,
                    autocommit=True,
                    connect_timeout=10,
                    prepare_threshold=None,
                    row_factory=record_factory,
                    application_name="serviceplan",
                )
            except psycopg.Error:
                raise StorageError(
                    "Cannot connect to the configured PostgreSQL database. Check its availability and server-side secrets. No local database was substituted."
                ) from None
        return self.connection

    def _context(self, connection):
        connection.execute(sql.SQL("set local search_path to {}").format(sql.Identifier(self.schema)))
        connection.execute("set local statement_timeout='30s'")
        connection.execute("set local lock_timeout='30s'")

    @contextmanager
    def transaction(self):
        for attempt in range(2):
            conn = self._connect()
            yielded = False
            try:
                with conn.transaction():
                    self._context(conn)
                    # Same single-writer semantics as BEGIN IMMEDIATE, including seeding.
                    conn.execute("select pg_advisory_xact_lock(%s)", (self._lock,))
                    self._in_transaction = True
                    yielded = True
                    yield
                return
            except psycopg.Error as exc:
                conn.close()
                # A stale idle connection can fail during BEGIN/SET/lock, before any action ran.
                # Reconnect once only in that case. Never replay a body or an uncertain commit.
                if (
                    not yielded
                    and attempt == 0
                    and isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))
                ):
                    continue
                raise StorageError(
                    "The database operation could not be confirmed. Refresh saved changes before retrying; no local database was substituted."
                ) from None
            finally:
                self._in_transaction = False

    def execute(self, query, params=()):
        # Internal service statements use qmark bind placeholders; values always remain bound parameters.
        query = query.replace("?", "%s")
        if self._in_transaction:
            return self._connect().execute(query, params)
        attempts = 2 if query.lstrip().lower().startswith(("select", "show")) else 1
        for attempt in range(attempts):
            conn = self._connect()
            try:
                with conn.transaction():
                    self._context(conn)
                    return conn.execute(query, params)
            except psycopg.OperationalError:
                conn.close()
                if attempt + 1 == attempts:
                    raise StorageError(
                        "PostgreSQL is temporarily unavailable. Refresh to reconnect. Saved history was not reset."
                    ) from None
            except psycopg.Error:
                raise StorageError(
                    "The configured database could not complete the request. Check its schema migration and permissions."
                ) from None

    def executemany(self, query, rows):
        if not self._in_transaction:
            raise RuntimeError("Batch writes require an explicit transaction")
        cursor = self._connect().cursor()
        cursor.executemany(query.replace("?", "%s"), rows)
        return cursor

    def columns(self, table):
        return [
            r[0]
            for r in self.execute(
                "select column_name from information_schema.columns where table_schema=? and table_name=? order by ordinal_position",
                (self.schema, table),
            ).fetchall()
        ]

    def tables(self):
        return {
            r[0]
            for r in self.execute(
                "select table_name from information_schema.tables where table_schema=? and table_type='BASE TABLE'",
                (self.schema,),
            ).fetchall()
        }

    def frame(self, query, params=()):
        cursor = self.execute(query, params)
        return pd.DataFrame.from_records(cursor.fetchall(), columns=[c.name for c in cursor.description])

    def close(self):
        if self.connection:
            self.connection.close()
