"""Versioned ServicePlan-only offline schema migration."""

import argparse, getpass, os
from urllib.parse import urlsplit
from psycopg import sql
from .storage import PostgresStore, StorageError, validate_url
from .config import ROOT


def migrate(url, schema="serviceplan"):
    validate_url(url)
    if "-pooler" in (urlsplit(url).hostname or ""):
        raise StorageError("Use the direct connection for migration")
    db = PostgresStore(url, schema)
    try:
        with db.transaction():
            db.connection.execute(sql.SQL("create schema if not exists {}").format(sql.Identifier(schema)))
            tables = db.tables()
            if tables:
                if "meta" not in tables:
                    raise StorageError("Schema contains unrelated tables; refusing to modify it")
                v = db.execute("select value from meta where key='schema_version'").fetchone()
                if not v or v[0] != "1":
                    raise StorageError("Unknown ServicePlan schema version")
            for s in (ROOT / "migrations/001_serviceplan.sql").read_text().split(";"):
                if s.strip():
                    db.connection.execute(s)
            db.execute("insert into meta values ('schema_version','1') on conflict(key) do nothing")
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", action="store_true")
    p.add_argument("--schema", default="serviceplan")
    p.add_argument("--seed", action="store_true")
    a = p.parse_args()
    url = (
        getpass.getpass("Direct ServicePlan database URL (hidden): ")
        if a.prompt
        else os.environ.get("SERVICEPLAN_DATABASE_URL_DIRECT")
    )
    if not url:
        p.error("Set SERVICEPLAN_DATABASE_URL_DIRECT privately or use --prompt")
    try:
        migrate(url, a.schema)
        if a.seed:
            from .service import Service

            s = Service(database_url=url, database_schema=a.schema)
            s.db.close()
        print("ServicePlan migration complete; existing history preserved.")
    except (StorageError, ValueError, OSError):
        p.exit(
            1,
            "Could not initialize ServicePlan. Check the private direct connection and schema. No credentials printed.\n",
        )


if __name__ == "__main__":
    main()
