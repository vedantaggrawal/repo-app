"""Tenant-scoped items API. Isolation is enforced by Postgres RLS, not by query filters.

x-tenant-id (set by the Gateway from the JWT) maps to the RLS uuid via
uuid5(NAMESPACE_URL, "eve-tenant:" + x-tenant-id).
Connection settings come from libpq env (PGHOST, PGDATABASE, PGUSER, PGPASSWORD).
"""
import uuid
from contextlib import contextmanager

from fastapi import FastAPI, Header, HTTPException
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

pool = ConnectionPool(open=False, min_size=1, max_size=5)
app = FastAPI(on_startup=[pool.open], on_shutdown=[pool.close])


class ItemIn(BaseModel):
    name: str


def tenant_uuid(x_tenant_id: str | None) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(401, "missing x-tenant-id")
    return uuid.uuid5(uuid.NAMESPACE_URL, "eve-tenant:" + x_tenant_id)


@contextmanager
def tenant_tx(tenant: uuid.UUID):
    """One transaction per request; the tenant is transaction-local (fail closed)."""
    with pool.connection() as conn, conn.transaction():
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
        yield conn


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/items")
def list_items(x_tenant_id: str | None = Header(None)):
    with tenant_tx(tenant_uuid(x_tenant_id)) as conn:
        rows = conn.execute("SELECT id, name, created_at FROM items ORDER BY created_at, id").fetchall()
    return [{"id": str(i), "name": n, "created_at": c.isoformat()} for i, n, c in rows]


@app.post("/items", status_code=201)
def create_item(item: ItemIn, x_tenant_id: str | None = Header(None)):
    tenant = tenant_uuid(x_tenant_id)
    with tenant_tx(tenant) as conn:
        row = conn.execute(
            "INSERT INTO items (tenant_id, name) VALUES (%s, %s) RETURNING id, name", (tenant, item.name)
        ).fetchone()
    return {"id": str(row[0]), "name": row[1]}
