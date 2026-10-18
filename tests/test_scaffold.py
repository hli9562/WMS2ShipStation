import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from wms2ship.config import Settings
from wms2ship.main import create_app


def test_migrations_restart_and_foreign_keys(tmp_path):
    settings = Settings(data_dir=tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert "Workspace ready" in client.get("/").text
        with app.state.engine.begin() as db:
            assert db.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            db.execute(
                text(
                    "INSERT INTO orders (id,wms_order_no,created_at,updated_at) "
                    "VALUES ('o','WMS-TEST','now','now')"
                )
            )
        with pytest.raises(IntegrityError), app.state.engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO packages(id,order_id,source_package_key) "
                    "VALUES ('p','missing','1')"
                )
            )
        settings.labels_dir.joinpath("test.txt").write_text("artifact survives restart")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        with sqlite3.connect(tmp_path / "app.sqlite3") as db:
            assert db.execute("SELECT wms_order_no FROM orders").fetchone() == ("WMS-TEST",)
            assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0005",)
        assert settings.labels_dir.joinpath("test.txt").read_text() == "artifact survives restart"


def test_host_and_mutation_protection(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/health", headers={"host": "evil.example"}).status_code == 400
        assert client.post("/api/imports").status_code == 403
        token = client.app.state.csrf_token
        assert (
            client.post(
                "/api/imports", headers={"x-csrf-token": token, "origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.get("/").headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("layout", ["local_us_units", "upstream_voids"])
def test_upgrade_preserves_both_early_0004_database_layouts(tmp_path, layout):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)):
        pass
    with sqlite3.connect(tmp_path / "app.sqlite3") as db:
        db.execute(
            "INSERT INTO orders (id,wms_order_no,created_at,updated_at) "
            "VALUES ('saved-order','PRESERVE-ME','now','now')"
        )
        db.execute(
            "INSERT INTO packages (id,order_id,source_package_key,weight_g,weight_oz) "
            "VALUES ('saved-package','saved-order','1',454,16)"
        )
        if layout == "local_us_units":
            db.execute("ALTER TABLE labels DROP COLUMN void_status")
            db.execute("ALTER TABLE labels DROP COLUMN void_updated_at")
        else:
            for name in ("weight_oz", "length_in", "width_in", "height_in"):
                db.execute(f"ALTER TABLE packages DROP COLUMN {name}")
        db.execute("UPDATE alembic_version SET version_num='0004'")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        with sqlite3.connect(tmp_path / "app.sqlite3") as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0005",)
            assert db.execute("SELECT wms_order_no FROM orders").fetchone() == ("PRESERVE-ME",)
            assert db.execute("SELECT weight_g FROM packages").fetchone() == (454,)
            expected = 16 if layout == "local_us_units" else None
            assert db.execute("SELECT weight_oz FROM packages").fetchone() == (expected,)
            label_columns = {row[1] for row in db.execute("PRAGMA table_info(labels)")}
            assert {"void_status", "void_updated_at"} <= label_columns
