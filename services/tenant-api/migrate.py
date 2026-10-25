"""Apply db/migrations/*.sql once each, in order, as the owner role (PG* env)."""
import pathlib

import psycopg

with psycopg.connect(autocommit=True) as conn:
    conn.execute("SELECT pg_advisory_lock(7201)")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
    for f in sorted(pathlib.Path("/migrations").glob("*.sql")):
        if conn.execute("SELECT 1 FROM schema_migrations WHERE name = %s", (f.name,)).fetchone():
            continue
        with conn.transaction():
            conn.execute(f.read_text())
            conn.execute("INSERT INTO schema_migrations VALUES (%s)", (f.name,))
        print("applied", f.name)
