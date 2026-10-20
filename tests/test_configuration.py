from datetime import date

import pytest
from fastapi.testclient import TestClient

from tests.test_imports import upload, workbook
from wms2ship.config import Settings
from wms2ship.main import create_app
from wms2ship.shipstation import build_payload


def test_package_edits_preview_save_reimport_and_provider_payload(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        endpoint = f"/api/orders/{order_id}"
        original = client.get(endpoint).json()
        config = draft(original)
        config["package"] = {
            "id": original["packages"][0]["id"],
            "weight_g": 1250,
            "length_mm": 315,
            "width_mm": 220,
            "height_mm": 105,
        }
        headers = {"x-csrf-token": client.app.state.csrf_token}
        ready = client.post(f"{endpoint}/readiness", json=config, headers=headers)
        assert ready.status_code == 200
        assert ready.json()["valid"], ready.json()
        assert client.get(endpoint).json()["packages"] == original["packages"]
        saved = client.patch(endpoint, json=config, headers=headers)
        assert saved.status_code == 200
        package = saved.json()["packages"][0]
        assert all(package[key] == value for key, value in config["package"].items())
        assert saved.json()["version"] == original["version"] + 1
        payload = build_payload(saved.json())
        assert payload["weight"]["units"] == "ounces"
        assert payload["weight"]["value"] == 45
        assert payload["dimensions"]["units"] == "inches"
        for name, rounded in (("length", 13), ("width", 9), ("height", 5)):
            assert payload["dimensions"][name] == rounded
        stale = client.patch(endpoint, json=config, headers=headers)
        assert stale.status_code == 409
        upload(client, workbook())
        assert client.get(endpoint).json()["packages"][0] == package


@pytest.mark.parametrize("field", ["weight_g", "length_mm", "width_mm", "height_mm"])
@pytest.mark.parametrize("value", [0, -1, 1.5])
def test_invalid_package_measurements_do_not_save(tmp_path, field, value):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        endpoint = f"/api/orders/{client.get('/api/orders').json()[0]['id']}"
        original = client.get(endpoint).json()
        config = draft(original)
        config["package"] = {
            key: original["packages"][0][key]
            for key in ("id", "weight_g", "length_mm", "width_mm", "height_mm")
        }
        config["package"][field] = value
        headers = {"x-csrf-token": client.app.state.csrf_token}
        assert client.post(f"{endpoint}/readiness", json=config, headers=headers).status_code == 422
        assert client.patch(endpoint, json=config, headers=headers).status_code == 422
        assert client.get(endpoint).json() == original


def test_package_edit_cannot_change_another_order(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook(order="FIRST"))
        upload(client, workbook(order="SECOND"))
        orders = client.get("/api/orders").json()
        original = [client.get(f"/api/orders/{o['id']}").json() for o in orders]
        config = draft(original[0])
        config["package"] = {
            "id": original[1]["packages"][0]["id"],
            "weight_g": 1250, "length_mm": 315, "width_mm": 220, "height_mm": 105,
        }
        endpoint = f"/api/orders/{original[0]['id']}"
        headers = {"x-csrf-token": client.app.state.csrf_token}
        assert client.post(f"{endpoint}/readiness", json=config, headers=headers).status_code == 422
        assert client.patch(endpoint, json=config, headers=headers).status_code == 422
        assert [client.get(f"/api/orders/{o['id']}").json() for o in orders] == original


def test_us_measurements_round_up_for_carrier_and_reimport(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        endpoint = f"/api/orders/{client.get('/api/orders').json()[0]['id']}"
        original = client.get(endpoint).json()
        config = draft(original)
        us = {"weight_oz": 16, "length_in": 10.25, "width_in": 7.5, "height_in": 4}
        config["package"] = {
            key: original["packages"][0][key]
            for key in ("id", "weight_g", "length_mm", "width_mm", "height_mm")
        }
        config["package"]["us_units"] = us
        headers = {"x-csrf-token": client.app.state.csrf_token}
        ready = client.post(f"{endpoint}/readiness", json=config, headers=headers)
        assert ready.status_code == 200
        assert ready.json()["valid"], ready.json()
        assert client.get(endpoint).json()["packages"] == original["packages"]
        saved = client.patch(endpoint, json=config, headers=headers)
        assert saved.status_code == 200
        package = saved.json()["packages"][0]
        assert {key: package[key] for key in us} == {
            "weight_oz": 16, "length_in": 11, "width_in": 8, "height_in": 4
        }
        payload = build_payload(saved.json())
        assert payload["weight"] == {"value": 16, "units": "ounces"}
        assert payload["dimensions"] == {
            "units": "inches", "length": 11, "width": 8, "height": 4
        }
        upload(client, workbook())
        assert client.get(endpoint).json()["packages"][0] == package
        config["version"] = saved.json()["version"]
        config["package"]["us_units"]["weight_oz"] = 0
        assert client.patch(endpoint, json=config, headers=headers).status_code == 422


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
        config["shipping"].pop("timezone")
        saved = client.patch(f"/api/orders/{order_id}", json=config, headers=headers)
        assert saved.status_code == 200
        assert saved.json()["version"] == 2
        assert saved.json()["shipping"]["timezone"] == "America/Chicago"
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


def test_shipper_address_overrides_manual_timezone(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        config = draft(client.get(f"/api/orders/{order_id}").json())
        config["shipping"]["timezone"] = "America/Los_Angeles"
        config["origin"].update(city="katy", state="Texas", country="United States")
        saved = client.patch(
            f"/api/orders/{order_id}",
            json=config,
            headers={"x-csrf-token": client.app.state.csrf_token},
        )
        assert saved.status_code == 200
        assert saved.json()["shipping"]["timezone"] == "America/Chicago"


@pytest.mark.parametrize("enabled", [False, True])
def test_configured_account_uses_explicit_live_setting(tmp_path, enabled):
    settings = Settings(
        data_dir=tmp_path,
        SHIPSTATION_API_KEY="dummy-key",
        SHIPSTATION_API_SECRET="dummy-secret",
        enable_live_purchase=enabled,
    )
    with TestClient(create_app(settings)) as client:
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        config = draft(client.get(f"/api/orders/{order_id}").json())
        config["shipping"]["provider"] = "shipstation"
        saved = client.patch(
            f"/api/orders/{order_id}",
            json=config,
            headers={"x-csrf-token": client.app.state.csrf_token},
        )
        assert saved.status_code == 200
        assert saved.json()["shipping"]["provider"] == (
            "shipstation" if enabled else "shipstation_test"
        )
        assert client.app.state.providers["shipstation"].enable_live is enabled


def test_draft_readiness_checks_without_saving(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        order = client.get(f"/api/orders/{order_id}").json()
        config = draft(order)
        headers = {"x-csrf-token": client.app.state.csrf_token}
        url = f"/api/orders/{order_id}/readiness"
        ready = client.post(url, json=config, headers=headers)
        assert ready.status_code == 200
        assert ready.json()["valid"] is True
        config["origin"]["phone"] = ""
        assert client.post(url, json=config, headers=headers).json()["valid"] is True
        config["origin"]["address1"] = ""
        blocked = client.post(url, json=config, headers=headers).json()
        assert blocked["valid"] is False
        assert any(issue["field"] == "origin.address1" for issue in blocked["issues"])
        unchanged = client.get(f"/api/orders/{order_id}").json()
        assert unchanged["version"] == order["version"]
        assert unchanged["origin"] == order["origin"]
        config["version"] += 1
        assert client.post(url, json=config, headers=headers).status_code == 409
        assert client.get("/api/history").json() == []
