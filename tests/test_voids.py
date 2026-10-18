from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_purchases import setup_order
from wms2ship.config import Settings
from wms2ship.main import create_app


def test_local_removal_needs_no_provider_and_preserves_history(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        order, headers, payload = setup_order(client)
        purchase_url = f"/api/orders/{order}/label-attempts"
        attempt = client.post(purchase_url, headers=headers, json=payload).json()
        label = attempt["labels"][0]["id"]
        url = f"/api/labels/{label}/void"
        assert client.post(url, json={"confirm_void": True}).status_code == 403
        assert client.post(url, headers=headers, json={}).status_code == 400
        # Real test labels use -1; local removal also works without any provider configured.
        with client.app.state.engine.begin() as db:
            db.execute(text("UPDATE labels SET provider_shipment_id='-1'"))
        provider = client.app.state.providers.pop("fake")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: client.post(url, headers=headers, json={"confirm_void": True}),
                    range(2),
                )
            )
        assert all(r.status_code == 200 for r in results)
        client.app.state.providers["fake"] = provider
        history = client.get("/api/history").json()[0]
        assert history["void_status"] == "voided"
        assert history["state"] == "removed"
        assert history["purchase_state"] == "purchased"
        assert client.get("/api/orders").json()[0]["label_status"] == "removed"
        review = client.get("/api/review?state=removed").json()
        assert review["rows"][0]["state"] == "removed"
        assert review["summary"]["purchased"] == 1
        assert client.get("/api/review").json()["rows"][0]["void_status"] == "voided"
        assert client.get(f"/api/labels/{label}/pdf").status_code == 409
        with client.app.state.engine.connect() as db:
            assert db.execute(text("SELECT count(*) FROM labels")).scalar() == 1
            assert db.execute(text("SELECT count(*) FROM purchase_guards")).scalar() == 0
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM attempt_events "
                        "WHERE event_type='label_removed_locally'"
                    )
                ).scalar()
                == 1
            )
        payload["request_token"] = str(uuid4())
        assert client.post(purchase_url, headers=headers, json=payload).status_code == 200
    with TestClient(create_app(settings)) as client:
        rows = client.get("/api/history").json()
        assert next(r for r in rows if r["label_id"] == label)["void_status"] == "voided"
