from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.test_imports import upload, workbook
from wms2ship.config import Settings
from wms2ship.main import create_app
from wms2ship.ship_dates import default_ship_date


@pytest.mark.parametrize(
    "timestamp,expected",
    [
        ("2026-10-16T16:59:59-05:00", "2026-10-16"),
        ("2026-10-16T17:00:00-05:00", "2026-10-19"),
        ("2026-10-16T23:00:00-05:00", "2026-10-19"),
        ("2026-10-17T09:00:00-05:00", "2026-10-19"),
        ("2026-10-18T19:00:00-05:00", "2026-10-19"),
        ("2026-10-19T16:00:00-05:00", "2026-10-19"),
        ("2026-10-19T17:01:00-05:00", "2026-10-20"),
        # Use Katy time, even if the computer/server is in UTC. DST changes in November.
        ("2026-10-19T21:59:59+00:00", "2026-10-19"),
        ("2026-10-19T22:00:00+00:00", "2026-10-20"),
        ("2026-11-02T22:59:59+00:00", "2026-11-02"),
        ("2026-11-02T23:00:00+00:00", "2026-11-03"),
    ],
)
def test_ship_date_cutoff_weekends_and_timezone(timestamp, expected):
    assert default_ship_date(datetime.fromisoformat(timestamp)) == expected


def test_order_exposes_default_without_saving_shipping(tmp_path, monkeypatch):
    monkeypatch.setattr("wms2ship.import_routes.default_ship_date", lambda: "2026-10-19")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        order = client.get(f"/api/orders/{order_id}").json()
        assert order["default_ship_date"] == "2026-10-19"
        assert order["shipping"] is None
        assert order["version"] == 1
