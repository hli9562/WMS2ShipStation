"""Seed Apex as the default shipper when no contacts have been configured."""

import json

from alembic import op
from sqlalchemy import text

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


APEX_ADDRESS = {
    "name": "Apex Tech",
    "company": "Apex Technology Distribution Inc",
    "phone": "",
    "address1": "20436 Westfield Commerce Dr",
    "address2": "",
    "city": "Katy",
    "state": "TX",
    "postal": "77494",
    "country": "US",
}


def upgrade():
    op.get_bind().execute(
        text(
            "INSERT INTO shipper_contacts (id,label,address_json,is_default) "
            "SELECT :id,:label,:address,1 "
            "WHERE NOT EXISTS (SELECT 1 FROM shipper_contacts)"
        ),
        {
            "id": "a9e10000-0000-4000-8000-000000000001",
            "label": "Apex Tech",
            "address": json.dumps(APEX_ADDRESS),
        },
    )


def downgrade():
    # Contact edits may already be in use; retain them when downgrading.
    pass
