import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_purchases import setup_order
from wms2ship.config import Settings
from wms2ship.main import create_app
from wms2ship.providers import FakeProvider, VoidRejected, VoidUncertain
from wms2ship.shipstation import ShipStationProvider


@pytest.mark.parametrize("outcome", ["approved", "rejected", "uncertain"])
def test_manual_void_preserves_history_and_guards(tmp_path, outcome):
    class Provider(FakeProvider):
        calls = 0

        def void_label(self, shipment_id):
            self.calls += 1
            if outcome == "rejected":
                raise VoidRejected()
            if outcome == "uncertain":
                raise VoidUncertain()

    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        provider = Provider()
        client.app.state.providers["fake"] = provider
        order, headers, payload = setup_order(client)
        purchase_url = f"/api/orders/{order}/label-attempts"
        attempt = client.post(purchase_url, headers=headers, json=payload).json()
        label = attempt["labels"][0]["id"]
        url = f"/api/labels/{label}/void"
        assert client.post(url, json={"confirm_void": True}).status_code == 403
        assert client.post(url, headers=headers, json={}).status_code == 400
        assert provider.calls == 0
        response = client.post(url, headers=headers, json={"confirm_void": True})
        status = "voided" if outcome == "approved" else outcome
        assert response.json()["void_status"] == status
        assert provider.calls == 1
        history = client.get("/api/history").json()[0]
        assert history["state"] == "purchased"
        assert history["void_status"] == status
        assert client.get("/api/review").json()["rows"][0]["void_status"] == status
        assert client.get(f"/api/labels/{label}/pdf").status_code == (
            200 if outcome == "rejected" else 409
        )
        with client.app.state.engine.connect() as db:
            assert db.execute(text("SELECT count(*) FROM labels")).scalar() == 1
            assert db.execute(text("SELECT count(*) FROM purchase_guards")).scalar() == (
                0 if outcome == "approved" else 1
            )
        if outcome != "rejected":
            again = client.post(url, headers=headers, json={"confirm_void": True})
            assert again.status_code == (200 if outcome == "approved" else 409)
            assert provider.calls == 1
        if outcome == "uncertain":
            payload["request_token"] = str(uuid4())
            assert client.post(purchase_url, headers=headers, json=payload).status_code == 409
            assert (
                client.post(
                    url + "/resolve",
                    headers=headers,
                    json={
                        "outcome": "voided",
                        "evidence": "Verified voided shipment in ShipStation account.",
                    },
                ).json()["void_status"]
                == "voided"
            )
        if outcome != "rejected":
            payload["request_token"] = str(uuid4())
            assert client.post(purchase_url, headers=headers, json=payload).status_code == 200
    with TestClient(create_app(settings)) as client:
        records = client.get("/api/history").json()
        assert next(r for r in records if r["label_id"] == label)["void_status"] == (
            "rejected" if outcome == "rejected" else "voided"
        )


@pytest.mark.parametrize(
    "body,code,error",
    [
        ({"approved": True}, 200, None),
        ({"approved": False}, 200, VoidRejected),
        ({"approved": "true"}, 200, VoidUncertain),
        ({}, 200, VoidUncertain),
        ({}, 503, VoidUncertain),
        ({}, 401, VoidRejected),
    ],
)
def test_shipstation_void_contract(body, code, error):
    def respond(request):
        assert request.url.path == "/shipments/voidlabel"
        assert json.loads(request.content) == {"shipmentId": 123}
        return httpx.Response(code, json=body)

    provider = ShipStationProvider("key", "secret", transport=httpx.MockTransport(respond))
    try:
        if error:
            with pytest.raises(error):
                provider.void_label("123")
        else:
            provider.void_label("123")
    finally:
        provider.close()


def test_interrupted_void_requires_verification(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        order, headers, payload = setup_order(client)
        attempt = client.post(
            f"/api/orders/{order}/label-attempts", headers=headers, json=payload
        ).json()
        with client.app.state.engine.begin() as db:
            db.execute(text("UPDATE labels SET void_status='pending'"))
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/history").json()[0]["void_status"] == "uncertain"
        label = attempt["labels"][0]["id"]
        assert client.get(f"/api/labels/{label}/pdf").status_code == 409


def test_pending_void_blocks_duplicate_call_and_resolution(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()

    class SlowProvider(FakeProvider):
        calls = 0

        def void_label(self, shipment_id):
            self.calls += 1
            entered.set()
            assert release.wait(5)

    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        provider = SlowProvider()
        client.app.state.providers["fake"] = provider
        order, headers, payload = setup_order(client)
        attempt = client.post(
            f"/api/orders/{order}/label-attempts", headers=headers, json=payload
        ).json()
        label = attempt["labels"][0]["id"]
        url = f"/api/labels/{label}/void"
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(client.post, url, headers=headers, json={"confirm_void": True})
            try:
                assert entered.wait(5)
                assert (
                    client.post(url, headers=headers, json={"confirm_void": True}).status_code
                    == 409
                )
                assert (
                    client.post(
                        url + "/resolve",
                        headers=headers,
                        json={
                            "outcome": "voided",
                            "evidence": "Verified shipment status with provider.",
                        },
                    ).status_code
                    == 409
                )
                assert client.get(f"/api/labels/{label}/pdf").status_code == 409
            finally:
                release.set()
            assert task.result().json()["void_status"] == "voided"
        assert provider.calls == 1


def test_void_timeout_is_uncertain_and_is_not_retried():
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    provider = ShipStationProvider("key", "secret", transport=httpx.MockTransport(timeout))
    try:
        with pytest.raises(VoidUncertain):
            provider.void_label("123")
        assert len(calls) == 1
    finally:
        provider.close()
