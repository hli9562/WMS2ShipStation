"""Persist the preferred shipper contact."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE shipper_contacts ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0")
    op.execute(
        "UPDATE shipper_contacts SET is_default=1 WHERE (SELECT count(*) FROM shipper_contacts)=1"
    )
    op.execute(
        "CREATE UNIQUE INDEX one_default_shipper ON shipper_contacts(is_default) WHERE is_default=1"
    )


def downgrade():
    op.execute("DROP INDEX one_default_shipper")
    op.drop_column("shipper_contacts", "is_default")
