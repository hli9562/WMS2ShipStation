from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_configuration import draft
from tests.test_imports import upload, workbook
from wms2ship.config import Settings
from wms2ship.main import create_app
from wms2ship.providers import FakeProvider, PurchaseRejected, PurchaseUncertain


def setup_order(client, number="WMS-001"):
    upload(client, workbook(order=number))
    order_id = next(
        o["id"] for o in client.get("/api/orders").json() if o["wms_order_no"] == number
    )
    order = client.get(f"/api/orders/{order_id}").json()
    headers = {"x-csrf-token": client.app.state.csrf_token}
    order = client.patch(f"/api/orders/{order_id}", json=draft(order), headers=headers).json()
    payload = {
        "version": order["version"],
        "package_id": order["packages"][0]["id"],
        "request_token": str(uuid4()),
        "confirm_purchase": True,
    }
    return order_id, headers, payload


def test_double_click_and_package_guard(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        order_id, headers, payload = setup_order(client)
        url = f"/api/orders/{order_id}/label-attempts"
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(lambda _: client.post(url, json=payload, headers=headers), range(2))
            )
        assert all(r.status_code == 200 for r in responses)
        assert responses[0].json()["id"] == responses[1].json()["id"]
        assert (
            client.get(f"/api/label-attempts/{responses[0].json()['id']}").json()["state"]
            == "purchased"
        )
        payload["request_token"] = str(uuid4())
        assert client.post(url, json=payload, headers=headers).status_code == 409
        with client.app.state.engine.connect() as db:
            assert db.execute(text("SELECT count(*) FROM labels")).scalar() == 1
            assert db.execute(text("SELECT count(*) FROM purchase_guards")).scalar() == 1


class FailingProvider(FakeProvider):
    def create_label(self, snapshot, attempt_id):
        raise PurchaseRejected()


class UncertainProvider(FakeProvider):
    def create_label(self, snapshot, attempt_id):
        raise PurchaseUncertain()


def test_rejection_releases_guard_but_uncertain_requires_reconciliation(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        order_id, headers, payload = setup_order(client)
        url = f"/api/orders/{order_id}/label-attempts"
        client.app.state.providers["fake"] = FailingProvider()
        assert client.post(url, json=payload, headers=headers).json()["state"] == "failed"
        client.app.state.providers["fake"] = UncertainProvider()
        payload["request_token"] = str(uuid4())
        uncertain = client.post(url, json=payload, headers=headers).json()
        assert uncertain["state"] == "uncertain"
        payload["request_token"] = str(uuid4())
        assert client.post(url, json=payload, headers=headers).status_code == 409
        reconciled = client.post(
            f"/api/label-attempts/{uncertain['id']}/reconcile",
            headers=headers,
            json={
                "outcome": "confirmed_not_purchased",
                "evidence": "Operator verified no purchase with provider support.",
            },
        )
        assert reconciled.json()["state"] == "failed"
        client.app.state.providers["fake"] = FakeProvider()
        assert client.post(url, json=payload, headers=headers).json()["state"] == "purchased"


def test_snapshot_cross_order_stale_and_missing_artifact(tmp_path, monkeypatch):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        order_id, headers, payload = setup_order(client)
        other_id, _, other_payload = setup_order(client, "WMS-002")
        url = f"/api/orders/{order_id}/label-attempts"
        wrong = {**payload, "package_id": other_payload["package_id"]}
        assert client.post(url, json=wrong, headers=headers).status_code == 422
        assert (
            client.post(url, json={**payload, "version": 100}, headers=headers).status_code == 409
        )

        def storage_failure(*args):
            raise OSError("simulated disk failure")

        monkeypatch.setattr("wms2ship.purchases.store_pdf", storage_failure)
        result = client.post(url, json=payload, headers=headers).json()
        assert result["state"] == "purchased"
        assert result["error_code"] == "artifact_recovery_required"
        assert (
            client.post(
                f"/api/orders/{other_id}/label-attempts", json=payload, headers=headers
            ).status_code
            == 409
        )
        payload["request_token"] = str(uuid4())
        assert client.post(url, json=payload, headers=headers).status_code == 409
        assert (
            client.post(
                f"/api/orders/{other_id}/label-attempts", json=other_payload, headers=headers
            ).json()["state"]
            == "purchased"
        )


def test_interrupted_attempt_blocks_after_restart(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        order_id, headers, payload = setup_order(client)
        result = client.post(
            f"/api/orders/{order_id}/label-attempts", json=payload, headers=headers
        ).json()
        with client.app.state.engine.begin() as db:
            db.execute(
                text("UPDATE label_attempts SET state='sending' WHERE id=:id"), {"id": result["id"]}
            )
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/label-attempts/{result['id']}").json()["state"] == "uncertain"
        headers = {"x-csrf-token": client.app.state.csrf_token}
        payload["request_token"] = str(uuid4())
        assert (
            client.post(
                f"/api/orders/{order_id}/label-attempts", json=payload, headers=headers
            ).status_code
            == 409
        )
