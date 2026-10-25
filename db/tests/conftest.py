"""Spin up a scratch database shaped like the platform's: demo_owner owns the
schema (no superuser, no BYPASSRLS), demo_app is the app role. Needs a Postgres
superuser in DATABASE_URL (CI: the service container)."""
import os
import pathlib

import psycopg
import pytest
from psycopg import conninfo, sql

ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
DB = "demo_rls_test"
PASSWORD = "test-only"
MIGRATIONS = sorted((pathlib.Path(__file__).parent.parent / "migrations").glob("*.sql"))


def _url(user):
    u = conninfo.conninfo_to_dict(ADMIN_URL)
    u.update(user=user, password=PASSWORD, dbname=DB)
    return conninfo.make_conninfo(**u)


@pytest.fixture(scope="session", autouse=True)
def database():
    admin = psycopg.connect(ADMIN_URL, autocommit=True)
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(DB)))
    for role in ("demo_owner", "demo_app"):
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        admin.execute(sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}"
        ).format(sql.Identifier(role), sql.Literal(PASSWORD)))
    admin.execute(sql.SQL("CREATE DATABASE {} OWNER demo_owner").format(sql.Identifier(DB)))
    with psycopg.connect(_url("demo_owner"), autocommit=True) as owner:
        for m in MIGRATIONS:
            owner.execute(m.read_text())
    yield
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(DB)))
    for role in ("demo_owner", "demo_app"):
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
    admin.close()


@pytest.fixture
def app():
    """One reused connection as the app role, like a pooled connection."""
    conn = psycopg.connect(_url("demo_app"))
    yield conn
    conn.rollback()   # never commit what a test left open
    conn.close()


@pytest.fixture
def owner():
    conn = psycopg.connect(_url("demo_owner"))
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture(autouse=True)
def clean(database):
    # TRUNCATE is not subject to row policies, so the owner can reset despite FORCE.
    with psycopg.connect(_url("demo_owner"), autocommit=True) as c:
        c.execute("TRUNCATE items")
