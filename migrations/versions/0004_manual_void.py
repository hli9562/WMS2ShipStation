"""Persist manual label void outcomes separately from purchase history."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE labels ADD COLUMN void_status TEXT NOT NULL DEFAULT 'active' "
        "CHECK (void_status IN ('active','pending','voided','rejected','uncertain'))"
    )
    op.execute("ALTER TABLE labels ADD COLUMN void_updated_at TEXT")


def downgrade():
    raise RuntimeError("History deletion is disabled; restore a backup instead.")
