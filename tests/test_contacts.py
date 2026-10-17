from fastapi.testclient import TestClient

from tests.test_configuration import draft
from tests.test_imports import upload, workbook
from wms2ship.config import Settings
from wms2ship.main import create_app


def test_contacts_persist_and_orders_keep_address_snapshot(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = {"x-csrf-token": client.app.state.csrf_token}
        upload(client, workbook())
        order_id = client.get("/api/orders").json()[0]["id"]
        config = draft(client.get(f"/api/orders/{order_id}").json())
        payload = {"label": "Warehouse contact", "address": config["origin"]}
        assert client.post("/api/shipper-contacts", json=payload).status_code == 403
        assert (
            client.post(
                "/api/shipper-contacts", json={**payload, "label": " "}, headers=headers
            ).status_code
            == 422
        )
        response = client.post("/api/shipper-contacts", json=payload, headers=headers)
        assert response.status_code == 201
        contact = response.json()
        config["origin"] = contact["address"]
        assert (
            client.patch(f"/api/orders/{order_id}", json=config, headers=headers).status_code == 200
        )
    with TestClient(create_app(settings)) as client:
        headers = {"x-csrf-token": client.app.state.csrf_token}
        assert client.get("/api/shipper-contacts").json() == [contact]
        payload["address"]["name"] = "New contact name"
        assert (
            client.put(
                f"/api/shipper-contacts/{contact['id']}", json=payload, headers=headers
            ).status_code
            == 200
        )
        assert client.get(f"/api/orders/{order_id}").json()["origin"]["name"] == "Test Warehouse"
        assert (
            client.delete(f"/api/shipper-contacts/{contact['id']}", headers=headers).status_code
            == 200
        )
        assert client.get("/api/shipper-contacts").json() == []
        assert client.get(f"/api/orders/{order_id}").json()["origin"]["name"] == "Test Warehouse"
        assert (
            client.put("/api/shipper-contacts/missing", json=payload, headers=headers).status_code
            == 404
        )


def test_contact_accepts_country_names_and_normalizes_state(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        headers = {"x-csrf-token": client.app.state.csrf_token}
        payload = {
            "label": "Synthetic shipper",
            "address": {
                "name": "Test contact",
                "country": "United States",
                "state": "tx",
                "city": "Katy",
                "postal": "77494",
            },
        }
        response = client.post("/api/shipper-contacts", json=payload, headers=headers)
        assert response.status_code == 201
        contact = response.json()
        assert contact["address"]["country"] == "US"
        assert contact["address"]["state"] == "TX"
        payload["address"].update(country=" united states of america ", state=" Texas ")
        updated = client.put(
            f"/api/shipper-contacts/{contact['id']}", json=payload, headers=headers
        )
        assert updated.status_code == 200
        assert updated.json()["address"]["country"] == "US"
        assert updated.json()["address"]["state"] == "TX"
        payload["address"]["country"] = "Not a country"
        invalid = client.post("/api/shipper-contacts", json=payload, headers=headers)
        assert invalid.status_code == 422
        assert invalid.json()["detail"][0]["loc"] == ["body", "address", "country"]
