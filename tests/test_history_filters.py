from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_purchases import setup_order
from wms2ship.config import Settings
from wms2ship.main import create_app


def test_history_wildcards_literal_characters_and_time_window(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        ids = []
        for number, timestamp in [
            ("HIST_%_01", "2026-10-17T10:00:00+00:00"),
            ("HIST-AB-02", "2026-10-18T10:00:00+00:00"),
        ]:
            order_id, headers, payload = setup_order(client, number)
            attempt = client.post(
                f"/api/orders/{order_id}/label-attempts", json=payload, headers=headers
            ).json()
            ids.append(order_id)
            with client.app.state.engine.begin() as db:
                db.execute(
                    text("UPDATE label_attempts SET created_at=:time WHERE id=:id"),
                    {"time": timestamp, "id": attempt["id"]},
                )

        def find(**params):
            r = client.get("/api/history", params=params)
            assert r.status_code == 200
            return r.json()

        assert len(find(search="hist")) == 2
        assert len(find(search="HIST*")) == 2
        assert find(search="HIST-??-0?")[0]["wms_order_no"] == "HIST-AB-02"
        assert len(find(search="HIST-??-0?")) == 1
        assert find(search="_%")[0]["wms_order_no"] == "HIST_%_01"
        assert len(find(search="_%")) == 1
        assert find(search="' OR 1=1--") == []
        assert len(find(search="SIMULATION")) == 2
        tracking = find(order_id=ids[0])[0]["tracking_number"]
        assert find(search="*" + tracking[-12:])[0]["order_id"] == ids[0]
        bounds = {"start": "2026-10-17T05:00:00-05:00", "end": "2026-10-17T10:00:00Z"}
        assert [r["order_id"] for r in find(**bounds)] == [ids[0]]
        assert len(find(search="HIST*", limit=1)) == 1
        assert find(search="HIST*", limit=1, offset=1)[0]["order_id"] == ids[0]
        assert find(search="HIST-??-0?", limit=1, offset=1) == []
        assert find(start="2026-10-19T00:00:00Z") == []
        assert find(order_id=ids[0], search="HIST-AB-*") == []
        assert (
            client.get(
                "/api/history",
                params={"start": "2026-10-18T00:00:00Z", "end": "2026-10-17T00:00:00Z"},
            ).status_code
            == 422
        )
        assert (
            client.get("/api/history", params={"start": "2026-10-17T00:00:00"}).status_code == 422
        )
