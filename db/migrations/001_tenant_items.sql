-- Sample tenant-scoped table with row-level security. Run as the owner/migrator
-- role (demo_owner), never as the app role (demo_app). Both roles come from the
-- platform's Postgres cluster; the app role has no BYPASSRLS and owns nothing.

CREATE TABLE items (
    tenant_id  uuid        NOT NULL,
    id         uuid        NOT NULL DEFAULT gen_random_uuid(),
    name       text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- Unique keys carry tenant_id: uniqueness is per tenant, and a clash never
    -- reveals that another tenant uses the same value.
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, name)
);

ALTER TABLE items ENABLE ROW LEVEL SECURITY;
-- Without FORCE the table owner skips every policy.
ALTER TABLE items FORCE ROW LEVEL SECURITY;

-- The tenant is set per transaction (SET LOCAL / set_config(..., true)).
-- current_setting(..., true) is NULL when the setting was never set, and ''
-- after a transaction that set it has ended on the same connection; NULLIF
-- turns both into NULL, so no tenant matches no rows (fail closed, no error).
CREATE POLICY tenant_isolation ON items
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

GRANT USAGE ON SCHEMA public TO demo_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON items TO demo_app;
