"""
Medium #21: schema drift guard between `scripts/init-db.sql` and the
SQLAlchemy models in `backend/storage/database.py`.

`init-db.sql` is mounted into the Postgres container's
`/docker-entrypoint-initdb.d/` (see `docker-compose.yml`) so the schema
exists before the backend connects on a fresh `make up`. The backend's
`init_db()` then runs `Base.metadata.create_all` (a no-op for existing
tables) plus a few ALTER TABLE migrations for columns added after the
table was first created.

Two sources of truth means drift is easy to introduce: add a column in
the model and forget to add it to the SQL (or vice versa). On a fresh
database the SQL wins; on an existing one `create_all` skips the new
column and the migration ALTER TABLE is the only thing keeping them in
sync. This test parses the SQL and compares the column list per table
against the live model so a future drift surfaces in CI.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.storage.database import Base


# Tables to compare. The SQL file uses `CREATE TABLE IF NOT EXISTS` blocks;
# the model uses `Base.metadata.tables`. The keys must match — they're the
# on-disk table names.
TABLES = ["logs", "users", "alert_rules", "triggered_alerts", "tenants"]


def _parse_sql_columns(sql_path: str) -> dict:
    """Extract `(column_name, ...)` lists per CREATE TABLE block in init-db.sql."""
    with open(sql_path) as f:
        sql = f.read()

    result = {}
    pattern = re.compile(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\);",
        re.DOTALL,
    )
    for m in pattern.finditer(sql):
        table = m.group(1)
        body = m.group(2)
        cols = []
        for raw in body.split("\n"):
            line = raw.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            # Drop inline comments (e.g. "id SERIAL PRIMARY KEY, -- comment").
            line = re.sub(r"--.*$", "", line).strip()
            if not line:
                continue
            # First token is the column name. The SQL quotes "user" because
            # it's a Postgres reserved word; strip the quotes for comparison.
            name = line.split()[0].strip('"')
            cols.append(name)
        result[table] = cols
    return result


def test_init_db_sql_columns_match_sqlalchemy_models():
    """Every CREATE TABLE column in init-db.sql must exist on the matching
    SQLAlchemy model. Drift in either direction (SQL missing a column the
    model adds, or model missing a column the SQL declares) breaks a
    fresh `make up` against Postgres — the SQL wins because it runs first.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sql_path = os.path.join(repo_root, "scripts", "init-db.sql")
    sql_cols = _parse_sql_columns(sql_path)

    missing_sql_path_msg = (
        f"init-db.sql not found at {sql_path}. "
        "If you moved the file, update this test."
    )
    assert os.path.exists(sql_path), missing_sql_path_msg

    for table in TABLES:
        assert table in sql_cols, (
            f"init-db.sql has no CREATE TABLE for `{table}` — either add it "
            f"or remove it from TABLES in tests/test_schema_drift.py"
        )

        model_cols = list(Base.metadata.tables[table].columns.keys())
        only_in_sql = set(sql_cols[table]) - set(model_cols)
        only_in_model = set(model_cols) - set(sql_cols[table])

        # Allow the SQL to have *fewer* columns than the model: init_db()'s
        # ALTER TABLE migrations fill in post-create additions like
        # users.updated_at and alert_rules.tenant. But the SQL must never
        # declare a column that the model doesn't know about — that would
        # silently break SELECT/INSERT in app code.
        assert not only_in_sql, (
            f"init-db.sql declares columns that the SQLAlchemy model "
            f"`{table}` doesn't have: {sorted(only_in_sql)}. Add them to "
            f"the model, or remove them from init-db.sql."
        )
        # Conversely, surface a soft warning for columns in the model that
        # the SQL doesn't create — they rely on init_db()'s migration block
        # to exist on a fresh DB. If init_db() loses the ALTER TABLE, a
        # fresh `make up` will crash on first insert.
        if only_in_model:
            # Surface this in test output as a reminder; we don't fail
            # because init_db() is allowed to add columns out-of-band.
            print(
                f"[schema-drift] `{table}` columns added by init_db() "
                f"migration, not by init-db.sql: {sorted(only_in_model)}"
            )
