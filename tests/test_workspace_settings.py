import json
import stat

import httpx
from fastapi.testclient import TestClient

from tests.test_configuration import draft
from tests.test_imports import upload, workbook
from wms2ship import workspace_settings as workspace
from wms2ship.config import Settings
from wms2ship.main import create_app


def headers(client):
    return {"x-csrf-token": client.app.state.csrf_token}


def test_defaults_persist_without_changing_existing_order_configuration(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/settings").json()["shipping_defaults"]["residential"] is True
        upload(client, workbook())
        identity = client.get("/api/orders").json()[0]["id"]
        endpoint = "/api/orders/" + identity
        saved = client.patch(
            endpoint, json=draft(client.get(endpoint).json()), headers=headers(client)
        ).json()
        defaults = dict(
            carrier_code="demo",
            service_code="demo_express",
            package_code="demo_parcel",
            residential=True,
            confirmation="signature",
            insurance="carrier",
        )
        response = client.put(
            "/api/settings/shipping-defaults", json=defaults, headers=headers(client)
        )
        assert response.status_code == 200
        assert response.json()["shipping_defaults"] == defaults
        assert client.get(endpoint).json() == saved
        assert (
            client.put(
                "/api/settings/shipping-defaults",
                json={**defaults, "insurance": "other"},
                headers=headers(client),
            ).status_code
            == 422
        )
        assert client.put("/api/settings/shipping-defaults", json=defaults).status_code == 403
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/api/settings").json()["shipping_defaults"] == defaults


def test_package_template_crud_rounds_up_without_changing_packages(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        upload(client, workbook())
        identity = client.get("/api/orders").json()[0]["id"]
        original = client.get("/api/orders/" + identity).json()["packages"]
        payload = dict(name="Small box", length_in=10.1, width_in=7.5, height_in=4)
        response = client.post(
            "/api/settings/package-templates", json=payload, headers=headers(client)
        )
        assert response.status_code == 201
        row = response.json()["package_templates"][0]
        assert [row[k] for k in ("length_in", "width_in", "height_in")] == [11, 8, 4]
        assert (
            client.post(
                "/api/settings/package-templates",
                json={**payload, "name": "SMALL BOX"},
                headers=headers(client),
            ).status_code
            == 409
        )
        endpoint = "/api/settings/package-templates/" + row["id"]
        response = client.put(
            endpoint,
            json={**payload, "name": "Medium box", "length_in": 12},
            headers=headers(client),
        )
        assert response.status_code == 200
        assert response.json()["package_templates"][0]["length_in"] == 12
        assert client.get("/api/orders/" + identity).json()["packages"] == original
        assert client.delete(endpoint, headers=headers(client)).json()["package_templates"] == []
        assert client.delete(endpoint, headers=headers(client)).status_code == 404
        assert (
            client.post(
                "/api/settings/package-templates",
                json={**payload, "length_in": 0},
                headers=headers(client),
            ).status_code
            == 422
        )


def test_connection_verification_is_read_only_and_does_not_expose_remote_body():
    calls = []

    def good(request):
        calls.append(request)
        return httpx.Response(
            200, json=[] if request.url.path == "/carriers" else {"shipments": []}
        )

    result = workspace.verify_credentials("mock-key", "mock-secret", httpx.MockTransport(good))
    assert result["connected"]
    assert [r.url.path for r in calls] == ["/carriers", "/shipments"]
    assert all(r.method == "GET" for r in calls)
    result = workspace.verify_credentials(
        "mock-key",
        "mock-secret",
        httpx.MockTransport(
            lambda request: httpx.Response(401, text="mock-secret should never be returned")
        ),
    )
    assert not result["connected"] and result["status_code"] == 401
    assert "mock-secret" not in json.dumps(result)
    invalid = workspace.verify_credentials(
        "mock-key",
        "mock-secret",
        httpx.MockTransport(lambda request: httpx.Response(200, text="Unexpected login page")),
    )
    assert not invalid["connected"]


def test_validated_credentials_hot_swap_and_survive_restart(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path,
        SHIPSTATION_API_KEY="old-key",
        SHIPSTATION_API_SECRET="old-secret",
        enable_live_purchase=False,
    )
    success = dict(connected=True, message="Verified", checked_at="2026-10-19T12:00:00Z")
    monkeypatch.setattr(workspace, "verify_credentials", lambda key, secret: success)
    with TestClient(create_app(settings)) as client:
        old_source = client.app.state.shipment_source
        response = client.put(
            "/api/settings/shipstation",
            headers=headers(client),
            json={"api_key": "new-key", "api_secret": "new-secret"},
        )
        assert response.status_code == 200
        assert response.json()["connection"]["last_test"]["connected"]
        assert not client.app.state.providers["shipstation"].enable_live
        assert client.app.state.shipment_source is not old_source
        assert not old_source.client.is_closed  # Existing reads can finish.
        assert "new-key" not in response.text and "new-secret" not in response.text
        assert "old-secret" not in client.get("/api/settings").text
        path = workspace.credential_path(settings)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text())["api_key"] == "new-key"
        # Blank save never clears a working connection.
        assert (
            client.put("/api/settings/shipstation", json={}, headers=headers(client)).status_code
            == 422
        )
    assert old_source.client.is_closed
    with TestClient(
        create_app(
            Settings(
                data_dir=tmp_path,
                SHIPSTATION_API_KEY="stale-env-key",
                SHIPSTATION_API_SECRET="stale-env-secret",
            )
        )
    ) as client:
        assert client.app.state.settings.shipstation_api_key.get_secret_value() == "new-key"


def test_failed_credentials_leave_existing_connection_intact(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path,
        SHIPSTATION_API_KEY="working-key",
        SHIPSTATION_API_SECRET="working-secret",
    )
    failure = dict(
        connected=False,
        message="ShipStation returned HTTP 401.",
        status_code=401,
        checked_at="2026-10-19T12:00:00Z",
    )
    monkeypatch.setattr(workspace, "verify_credentials", lambda key, secret: failure)
    with TestClient(create_app(settings)) as client:
        original = client.app.state.shipment_source
        response = client.put(
            "/api/settings/shipstation",
            json={"api_key": "bad-key", "api_secret": "bad-secret"},
            headers=headers(client),
        )
        assert response.status_code == 422 and "bad-secret" not in response.text
        assert client.app.state.shipment_source is original
        assert not workspace.credential_path(settings).exists()
        tested = client.post("/api/settings/shipstation/test", json={}, headers=headers(client))
        assert tested.json()["status_code"] == 401
        assert client.get("/api/settings").json()["connection"]["last_test"]["connected"] is False
