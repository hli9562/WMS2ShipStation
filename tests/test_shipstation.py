import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_configuration import draft
from tests.test_purchases import setup_order
from wms2ship.config import Settings
from wms2ship.main import create_app
from wms2ship.providers import PurchaseRejected, PurchaseUncertain, demo_pdf
from wms2ship.shipstation import ProviderUnavailable, ShipStationProvider, build_payload


def snapshot():
    order = {
        "version": 1,
        "items": [{"id": "item", "quantity": 2}],
        "recipient": {
            "name": "Test",
            "address1": "100 Test Street",
            "city": "Test",
            "state": "AB",
            "postal": "T0A 0A0",
            "country": "CA",
        },
        "packages": [
            {"id": "package", "length_mm": 200, "width_mm": 185, "height_mm": 140, "weight_g": 460}
        ],
    }
    config = draft(order)
    order.update({key: config[key] for key in ("origin", "shipping", "customs")})
    return order


def test_payload_metric_units_customs_and_no_order_creation():
    payload = build_payload(snapshot())
    assert payload["weight"] == {"value": 460, "units": "grams"}
    assert payload["dimensions"]["width"] == 18.5
    assert payload["shipFrom"]["city"] == "Katy"
    assert payload["internationalOptions"]["customsItems"][0]["value"] == 10
    assert "orderId" not in payload
    assert payload["testLabel"] is False


def test_success_missing_pdf_and_no_purchase_retries():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/shipments/createlabel"
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(
            200,
            json={
                "shipmentId": 123,
                "trackingNumber": "TRACK-TEST",
                "shipmentCost": 12.34,
                "insuranceCost": 0,
                "labelData": base64.b64encode(demo_pdf()).decode(),
            },
        )

    provider = ShipStationProvider("test-key", "test-secret", True, httpx.MockTransport(handler))
    result = provider.create_label(snapshot(), "attempt")
    assert result.tracking == "TRACK-TEST"
    assert result.charge_minor == 1234
    assert result.pdf.startswith(b"%PDF-")
    assert len(calls) == 1
    provider.close()

    provider = ShipStationProvider(
        "k",
        "s",
        True,
        httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"shipmentId": 123, "trackingNumber": "T", "labelData": "invalid!"}
            )
        ),
    )
    assert provider.create_label(snapshot(), "a").pdf is None
    provider.close()


@pytest.mark.parametrize(
    "status,exception",
    [
        (400, PurchaseRejected),
        (401, PurchaseRejected),
        (429, PurchaseUncertain),
        (500, PurchaseUncertain),
        (302, PurchaseUncertain),
    ],
)
def test_error_classification(status, exception):
    provider = ShipStationProvider(
        "k",
        "s",
        True,
        httpx.MockTransport(
            lambda _: httpx.Response(status, text="Do not expose this provider body.")
        ),
    )
    with pytest.raises(exception):
        provider.create_label(snapshot(), "a")
    provider.close()


def test_timeout_and_malformed_success_remain_uncertain():
    def timeout(request):
        raise httpx.ReadTimeout("test", request=request)

    for transport in (
        httpx.MockTransport(timeout),
        httpx.MockTransport(lambda _: httpx.Response(200, json={"unexpected": True})),
    ):
        provider = ShipStationProvider("k", "s", True, transport)
        with pytest.raises(PurchaseUncertain):
            provider.create_label(snapshot(), "a")
        provider.close()


def test_account_discovery_and_redaction():
    def handler(request):
        paths = {
            "/stores": [{"marketplaceId": 0, "active": True}],
            "/carriers": [{"code": "test", "name": "Test Carrier", "primary": True}],
            "/carriers/listservices": [
                {"code": "service", "name": "Service", "international": True}
            ],
            "/carriers/listpackages": [{"code": "package", "name": "Package"}],
        }
        return httpx.Response(200, json=paths[request.url.path])

    provider = ShipStationProvider(
        "secret-key", "secret-value", transport=httpx.MockTransport(handler)
    )
    catalog = provider.catalog()
    assert catalog["carriers"][0]["services"][0]["code"] == "service"
    assert "secret" not in json.dumps(catalog)
    provider.close()
    provider = ShipStationProvider(
        "k", "s", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
    )
    with pytest.raises(ProviderUnavailable, match="Manual Store"):
        provider.catalog()
    provider.close()


def test_live_disabled_by_default_and_no_secret_in_http_output(tmp_path):
    settings = Settings(
        data_dir=tmp_path, SHIPSTATION_API_KEY="test-key", SHIPSTATION_API_SECRET="test-secret"
    )
    with TestClient(create_app(settings)) as client:
        providers = client.get("/api/providers").json()
        assert (
            next(p for p in providers if p["code"] == "shipstation")["live_purchase_enabled"]
            is False
        )
        assert "test-secret" not in json.dumps(providers)
        order_id, headers, payload = setup_order(client)
        order = client.get(f"/api/orders/{order_id}").json()
        config = draft(order)
        config["shipping"]["provider"] = "shipstation"
        saved = client.patch(f"/api/orders/{order_id}", json=config, headers=headers).json()
        payload["version"] = saved["version"]
        result = client.post(
            f"/api/orders/{order_id}/label-attempts", json=payload, headers=headers
        )
        assert result.status_code == 400
        assert "disabled" in result.json()["detail"]


def test_live_adapter_end_to_end_uses_mock_transport_only(tmp_path):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            assert request.url.path == "/shipments/createlabel"
            body = json.loads(request.content)
            assert body["shipTo"]["country"] == "CA"
            return httpx.Response(
                200,
                json={
                    "shipmentId": 123,
                    "trackingNumber": "MOCK-ONLY-TRACKING",
                    "shipmentCost": 1,
                    "labelData": base64.b64encode(demo_pdf()).decode(),
                },
            )
        return httpx.Response(
            200,
            json={
                "/stores": [{"marketplaceId": 0, "active": True}],
                "/carriers": [{"code": "demo", "name": "Mock carrier", "primary": True}],
                "/carriers/listservices": [
                    {"code": "demo_ground", "name": "Mock service", "international": True}
                ],
                "/carriers/listpackages": [{"code": "demo_parcel", "name": "Mock parcel"}],
            }[request.url.path],
        )

    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        client.app.state.providers["shipstation"] = ShipStationProvider(
            "mock-key", "mock-secret", True, httpx.MockTransport(handler)
        )
        order_id, headers, payload = setup_order(client)
        order = client.get(f"/api/orders/{order_id}").json()
        config = draft(order)
        config["shipping"]["provider"] = "shipstation"
        saved = client.patch(f"/api/orders/{order_id}", json=config, headers=headers).json()
        payload["version"] = saved["version"]
        result = client.post(
            f"/api/orders/{order_id}/label-attempts", json=payload, headers=headers
        )
        assert result.json()["state"] == "purchased", result.text
        assert result.json()["labels"][0]["tracking_number"] == "MOCK-ONLY-TRACKING"
        assert len([call for call in calls if call[0] == "POST"]) == 1
        label = result.json()["labels"][0]["id"]
        assert client.get(f"/api/labels/{label}/pdf").status_code == 200
        assert len([call for call in calls if call[0] == "POST"]) == 1
