"""Cross-tenant isolation of the items table, as the app role would hit it."""
import uuid

import psycopg
import pytest

A, B = str(uuid.uuid4()), str(uuid.uuid4())


def as_tenant(conn, tenant):
    """Scope the current transaction to a tenant (the SET LOCAL equivalent, bindable)."""
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))


def add(conn, tenant, name, tenant_id=None):
    as_tenant(conn, tenant)
    conn.execute("INSERT INTO items (tenant_id, name) VALUES (%s, %s)", (tenant_id or tenant, name))
    conn.commit()


def names(conn, tenant=None):
    if tenant:
        as_tenant(conn, tenant)
    rows = [r[0] for r in conn.execute("SELECT name FROM items ORDER BY name")]
    conn.commit()
    return rows


def test_each_tenant_reads_only_its_own_rows(app):
    add(app, A, "a1")
    add(app, B, "b1")
    assert names(app, A) == ["a1"]
    assert names(app, B) == ["b1"]


def test_tenant_cannot_insert_for_another_tenant(app):
    as_tenant(app, A)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app.execute("INSERT INTO items (tenant_id, name) VALUES (%s, 'x')", (B,))
    app.rollback()
    assert names(app, B) == []


def test_tenant_cannot_update_or_delete_another_tenants_rows(app):
    add(app, B, "b1")
    as_tenant(app, A)
    assert app.execute("UPDATE items SET name = 'hacked'").rowcount == 0
    assert app.execute("DELETE FROM items").rowcount == 0
    app.commit()
    assert names(app, B) == ["b1"]


def test_tenant_cannot_move_a_row_to_another_tenant(app):
    add(app, A, "a1")
    as_tenant(app, A)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app.execute("UPDATE items SET tenant_id = %s", (B,))
    app.rollback()
    assert names(app, A) == ["a1"]


def test_unset_context_sees_and_writes_nothing(app):
    add(app, A, "a1")
    assert names(app) == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app.execute("INSERT INTO items (tenant_id, name) VALUES (%s, 'x')", (A,))
    app.rollback()


def test_set_local_does_not_leak_to_the_next_transaction(app):
    """Same connection, as behind a transaction-pooling PgBouncer."""
    add(app, A, "a1")
    assert names(app, A) == ["a1"]                     # txn 1: tenant A, committed
    assert names(app) == []                            # txn 2: nothing set
    assert app.execute("SELECT current_setting('app.tenant_id', true)").fetchone()[0] in (None, "")
    app.rollback()
    as_tenant(app, A)                                  # rolled back txn must not leak either
    app.rollback()
    assert names(app) == []


def test_unique_keys_are_per_tenant(app):
    add(app, A, "same")
    add(app, B, "same")                                # same value, other tenant: fine
    as_tenant(app, A)
    with pytest.raises(psycopg.errors.UniqueViolation):
        app.execute("INSERT INTO items (tenant_id, name) VALUES (%s, 'same')", (A,))
    app.rollback()


def test_owner_is_subject_to_policies_because_of_force(app, owner):
    add(app, A, "a1")
    assert names(owner) == []                          # owner, no tenant: nothing
    as_tenant(owner, B)
    assert owner.execute("SELECT count(*) FROM items").fetchone()[0] == 0   # not A's rows
    owner.rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        owner.execute("INSERT INTO items (tenant_id, name) VALUES (%s, 'x')", (A,))   # no context
    owner.rollback()


def test_without_force_the_owner_would_bypass(app, owner):
    """Control: proves the previous test is what FORCE buys, not a quirk of the setup."""
    add(app, A, "a1")
    owner.execute("ALTER TABLE items NO FORCE ROW LEVEL SECURITY")
    seen = [r[0] for r in owner.execute("SELECT name FROM items")]
    owner.rollback()                                   # DDL is transactional: FORCE stays on
    assert seen == ["a1"]


def test_app_role_is_a_plain_non_owner(app):
    row = app.execute("""
        SELECT r.rolsuper, r.rolbypassrls, c.relowner = r.oid, c.relrowsecurity, c.relforcerowsecurity
        FROM pg_roles r, pg_class c
        WHERE r.rolname = current_user AND c.oid = 'items'::regclass""").fetchone()
    assert row == (False, False, False, True, True)
