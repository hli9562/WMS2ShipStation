"""Preserve US measurements and reconcile the two early local 0004 schemas."""

from alembic import op
from sqlalchemy import inspect

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # An unpublished local build used 0004 for US units before upstream added
    # manual removal as 0004. Preserve both existing database layouts.
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("labels")}
    if "void_status" not in columns:
        op.execute(
            "ALTER TABLE labels ADD COLUMN void_status TEXT NOT NULL DEFAULT 'active' "
            "CHECK (void_status IN ('active','pending','voided','rejected','uncertain'))"
        )
    if "void_updated_at" not in columns:
        op.execute("ALTER TABLE labels ADD COLUMN void_updated_at TEXT")
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("packages")}
    for name in ("weight_oz", "length_in", "width_in", "height_in"):
        if name not in columns:
            op.execute(f"ALTER TABLE packages ADD COLUMN {name} REAL CHECK ({name} > 0)")


def downgrade():
    raise RuntimeError("Measurement history deletion is disabled; restore a backup instead.")
