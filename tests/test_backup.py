import sqlite3

import pytest

from wms2ship.backup import create_backup, restore_backup
from wms2ship.config import Settings
from wms2ship.db import migrate


def test_backup_restore_preserves_history_and_artifacts(tmp_path):
    data = tmp_path / "data"
    migrate(Settings(data_dir=data))
    with sqlite3.connect(data / "app.sqlite3") as db:
        db.execute(
            "INSERT INTO orders(id,wms_order_no,created_at,updated_at) "
            "VALUES('o','WMS-TEST','now','now')"
        )
    (data / "labels" / "test.pdf").write_bytes(b"test artifact")
    archive = tmp_path / "backup.tar.gz"
    create_backup(data, archive)
    restored = tmp_path / "restored"
    restore_backup(restored, archive)
    with sqlite3.connect(restored / "app.sqlite3") as db:
        assert db.execute("SELECT wms_order_no FROM orders").fetchone() == ("WMS-TEST",)
    assert (restored / "labels" / "test.pdf").read_bytes() == b"test artifact"
    with pytest.raises(ValueError, match="empty"):
        restore_backup(restored, archive)
    with pytest.raises(ValueError, match="new backup"):
        create_backup(data, archive)
