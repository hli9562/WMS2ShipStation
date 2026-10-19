"""Workspace defaults and reusable package templates."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE workspace_preferences (
        id TEXT PRIMARY KEY, value_json TEXT NOT NULL CHECK (json_valid(value_json))
    )""")
    op.execute("""CREATE TABLE package_templates (
        id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        length_in INTEGER NOT NULL CHECK (length_in > 0),
        width_in INTEGER NOT NULL CHECK (width_in > 0),
        height_in INTEGER NOT NULL CHECK (height_in > 0)
    )""")


def downgrade():
    raise RuntimeError("Retain saved workspace settings; restore a backup to downgrade.")
