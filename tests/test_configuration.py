from datetime import date

from fastapi.testclient import TestClient

from tests.test_imports import upload, workbook
from wms2ship.config import Settings
from wms2ship.main import create_app


def draft(order):
    return {
        "version": order["version"],
        "origin": {
            "name": "Test Warehouse",
            "phone": "+15555550100",
            "address1": "100 Synthetic Street",
            "city": "Katy",
            "state": "TX",
            "postal": "77494",
            "country": "US",
        },
        "shipping": {
            "provider": "fake",
            "carrier_code": "demo",
            "service_code": "demo_ground",
            "package_code": "demo_parcel",
            "ship_date": date.today().isoformat(),
            "timezone": "America/Chicago",
            "residential": False,
            "confirmation": "none",
            "insurance": "none",
            "duties_payer": "recipient",
        },
        "customs": {
            "contents": "merchandise",
            "non_delivery": "return_to_sender",
            "items": [
                {
                    "item_id": order["items"][0]["id"],
                    "description": "Synthetic test item",
                    "quantity": 2,
                    "unit_value": "10.00",
                    "currency": "USD",
                    "country_of_origin": "US",
                    "hs_code": "123456",
                }
            ],
        },
    }


def test_per_order_configuration_and_stale_version(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        headers = {"x-csrf-token": client.app.state.csrf_token}
        check = client.post(f"/api/orders/{order_id}/validate", headers=headers).json()
        assert not check["valid"]
        order = client.get(f"/api/orders/{order_id}").json()
        config = draft(order)
        saved = client.patch(f"/api/orders/{order_id}", json=config, headers=headers)
        assert saved.status_code == 200
        assert saved.json()["version"] == 2
        assert (
            client.patch(f"/api/orders/{order_id}", json=config, headers=headers).status_code == 409
        )
        check = client.post(f"/api/orders/{order_id}/validate", headers=headers).json()
        assert check["valid"], check
        assert check["mode"] == "simulation"
        assert saved.json()["origin"]["address1"] == "100 Synthetic Street"


def test_customs_and_carrier_validation_blocks_purchase_readiness(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        headers = {"x-csrf-token": client.app.state.csrf_token}
        order = client.get(f"/api/orders/{order_id}").json()
        config = draft(order)
        config["origin"]["city"] = "Other City"
        config["shipping"]["service_code"] = "incompatible"
        config["customs"]["items"][0]["quantity"] = 3
        config["customs"]["items"][0]["unit_value"] = "NaN"
        config["customs"]["items"][0]["currency"] = "CAD"
        assert (
            client.patch(f"/api/orders/{order_id}", json=config, headers=headers).status_code == 200
        )
        check = client.post(f"/api/orders/{order_id}/validate", headers=headers).json()
        assert not check["valid"]
        fields = {issue["field"] for issue in check["issues"]}
        assert {
            "origin",
            "shipping.service_code",
            "customs.items",
            "customs.items.0.unit_value",
            "customs.items.0.currency",
        } <= fields


def test_existing_tracking_blocks_readiness_and_simulation_is_explicit(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook(tracking="EXISTING-TRACKING"))
        order_id = client.get("/api/orders").json()[0]["id"]
        headers = {"x-csrf-token": client.app.state.csrf_token}
        order = client.get(f"/api/orders/{order_id}").json()
        client.patch(f"/api/orders/{order_id}", json=draft(order), headers=headers)
        result = client.post(f"/api/orders/{order_id}/validate", headers=headers).json()
        assert any(i["field"] == "packages.source_tracking" for i in result["issues"])
        assert client.get("/api/providers/fake/carriers").json()["mode"] == "simulation"


def test_shipping_addons_persist_and_validate_carrier_scope(tmp_path):
    from wms2ship.configuration import validate_order

    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        order = client.get(f"/api/orders/{order_id}").json()
        config = draft(order)
        config["shipping"].update(
            insurance="parcelguard",
            insured_value="100.00",
            saturday_delivery=True,
            non_machinable=False,
            contains_alcohol=True,
        )
        response = client.patch(
            f"/api/orders/{order_id}",
            json=config,
            headers={"x-csrf-token": client.app.state.csrf_token},
        )
        assert response.status_code == 200
        saved = response.json()
        assert saved["shipping"]["insurance"] == "parcelguard"
        assert saved["shipping"]["saturday_delivery"] is True
        assert saved["shipping"]["non_machinable"] is False
        saved["shipping"].update(
            provider="shipstation", carrier_code="ups", confirmation="direct_signature"
        )
        catalog = {
            "provider": "shipstation",
            "carriers": [
                {
                    "code": "ups",
                    "services": [{"code": "demo_ground", "international": True}],
                    "packages": [{"code": "demo_parcel", "international": False}],
                }
            ],
        }
        issues = validate_order(saved, catalog)
        assert any(i["field"] == "shipping.package_code" for i in issues)
        assert any(i["field"] == "shipping.confirmation" for i in issues)
        saved["shipping"]["carrier_code"] = "fedex"
        catalog["carriers"][0]["code"] = "fedex"
        catalog["carriers"][0]["packages"][0]["international"] = True
        assert not validate_order(saved, catalog)
