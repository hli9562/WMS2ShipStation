"""Saved shipper contacts, copied into orders when selected."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE shipper_contacts (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL CHECK (length(trim(label)) > 0),
        address_json TEXT NOT NULL CHECK (json_valid(address_json))
    )""")


def downgrade():
    op.drop_table("shipper_contacts")
