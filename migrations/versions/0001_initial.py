"""Initial order, import, purchase and label schema."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE TABLE import_batches (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    parser_version TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(summary_json)),
    created_at TEXT NOT NULL
)"""
    )
    op.execute("""CREATE INDEX ix_import_batches_sha256 ON import_batches(sha256)""")
    op.execute(
        """CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    wms_order_no TEXT NOT NULL UNIQUE CHECK (length(trim(wms_order_no)) > 0),
    platform_reference TEXT,
    recipient_json TEXT CHECK (recipient_json IS NULL OR json_valid(recipient_json)),
    origin_json TEXT CHECK (origin_json IS NULL OR json_valid(origin_json)),
    shipping_json TEXT CHECK (shipping_json IS NULL OR json_valid(shipping_json)),
    customs_json TEXT CHECK (customs_json IS NULL OR json_valid(customs_json)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""
    )
    op.execute(
        """CREATE TABLE import_rows (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batches(id),
    sheet_name TEXT NOT NULL,
    row_number INTEGER NOT NULL CHECK (row_number > 0),
    source_order_no TEXT,
    order_id TEXT REFERENCES orders(id),
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    issues_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(issues_json)),
    UNIQUE (batch_id, sheet_name, row_number)
)"""
    )
    op.execute("""CREATE INDEX ix_import_rows_order ON import_rows(order_id)""")
    op.execute(
        """CREATE TABLE order_items (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    source_item_key TEXT NOT NULL,
    sku TEXT NOT NULL,
    description TEXT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    customs_json TEXT CHECK (customs_json IS NULL OR json_valid(customs_json)),
    UNIQUE (order_id, source_item_key)
)"""
    )
    op.execute(
        """CREATE TABLE packages (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    source_package_key TEXT NOT NULL,
    length_mm INTEGER CHECK (length_mm > 0),
    width_mm INTEGER CHECK (width_mm > 0),
    height_mm INTEGER CHECK (height_mm > 0),
    weight_g INTEGER CHECK (weight_g > 0),
    source_tracking TEXT,
    UNIQUE (order_id, source_package_key)
)"""
    )
    op.execute(
        """CREATE TABLE provider_accounts (
    id TEXT PRIMARY KEY,
    provider_code TEXT NOT NULL,
    display_name TEXT NOT NULL,
    credential_reference TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
)"""
    )
    op.execute(
        """CREATE TABLE label_attempts (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    provider_account_id TEXT NOT NULL REFERENCES provider_accounts(id),
    order_version INTEGER NOT NULL CHECK (order_version > 0),
    request_token TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('prepared','sending','purchased','failed','uncertain')),
    request_snapshot_json TEXT NOT NULL CHECK (json_valid(request_snapshot_json)),
    provider_evidence_json TEXT CHECK (provider_evidence_json IS NULL
        OR json_valid(provider_evidence_json)),
    error_code TEXT,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""
    )
    op.execute("""CREATE INDEX ix_label_attempts_order ON label_attempts(order_id, created_at)""")
    op.execute("""CREATE INDEX ix_label_attempts_state ON label_attempts(state)""")
    op.execute(
        """CREATE TABLE attempt_packages (
    attempt_id TEXT NOT NULL REFERENCES label_attempts(id),
    package_id TEXT NOT NULL REFERENCES packages(id),
    PRIMARY KEY (attempt_id, package_id)
)"""
    )
    op.execute("""CREATE INDEX ix_attempt_packages_package ON attempt_packages(package_id)""")
    op.execute(
        """CREATE TABLE purchase_guards (
    package_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id, package_id) REFERENCES attempt_packages(attempt_id, package_id)
)"""
    )
    op.execute("""CREATE INDEX ix_purchase_guards_attempt ON purchase_guards(attempt_id)""")
    op.execute(
        """CREATE TABLE labels (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    provider_shipment_id TEXT,
    provider_label_id TEXT,
    tracking_number TEXT,
    charge_minor INTEGER CHECK (charge_minor >= 0),
    currency TEXT CHECK (currency IS NULL OR length(currency) = 3),
    created_at TEXT NOT NULL,
    CHECK ((charge_minor IS NULL AND currency IS NULL)
        OR (charge_minor IS NOT NULL AND currency IS NOT NULL)),
    UNIQUE (attempt_id, package_id),
    FOREIGN KEY (attempt_id, package_id) REFERENCES attempt_packages(attempt_id, package_id)
)"""
    )
    op.execute("""CREATE INDEX ix_labels_tracking ON labels(tracking_number)""")
    op.execute(
        """CREATE TABLE label_artifacts (
    id TEXT PRIMARY KEY,
    label_id TEXT NOT NULL REFERENCES labels(id),
    kind TEXT NOT NULL CHECK (kind IN ('original','letter')),
    storage_key TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    byte_count INTEGER NOT NULL CHECK (byte_count > 0),
    created_at TEXT NOT NULL,
    UNIQUE (label_id, kind)
)"""
    )
    op.execute(
        """CREATE TABLE attempt_events (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES label_attempts(id),
    actor_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(evidence_json)),
    created_at TEXT NOT NULL
)"""
    )
    op.execute(
        """CREATE INDEX ix_attempt_events_attempt ON attempt_events(attempt_id, created_at)"""
    )


def downgrade():
    raise RuntimeError("History deletion is disabled; restore a backup instead.")
