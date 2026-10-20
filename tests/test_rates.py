import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_configuration import draft
from tests.test_imports import upload, workbook
from wms2ship.config import Settings
from wms2ship.main import create_app
from wms2ship.rates import rate_payload
from wms2ship.shipstation import (
    ProviderUnavailable,
    ShipStationProvider,
    ShipStationTestProvider,
    build_payload,
)


def catalog():
    return {
        "provider": "shipstation",
        "carriers": [
            {
                "code": code,
                "name": name,
                "services": [
                    {
                        "code": code + "_ground",
                        "name": name + " Ground",
                        "domestic": True,
                        "international": True,
                    },
                    {"code": code + "_2day", "name": name + " 2nd Day", "domestic": True},
                ],
                "packages": [
                    {"code": "package", "name": "Package"},
                    {"code": "flat_rate_box", "name": "Flat Rate Box"},
                ],
            }
            for code, name in [("stamps_com", "USPS"), ("ups", "UPS"), ("fedex", "FedEx")]
        ],
    }


def fake_response(request):
    assert request.url.path == "/shipments/getrates"
    code = json.loads(request.content)["carrierCode"]
    return httpx.Response(
        200,
        json=[
            {"serviceCode": code + "_2day", "shipmentCost": "20.00", "otherCost": "2.10"},
            {"serviceCode": code + "_ground", "shipmentCost": "8.25", "otherCost": "0.33"},
        ],
    )


def configured(client):
    upload(client, workbook())
    order = client.get("/api/orders/" + client.get("/api/orders").json()[0]["id"]).json()
    config = draft(order)
    config["shipping"].update(
        provider="shipstation",
        carrier_code="",
        service_code="",
        package_code="",
        residential=True,
        confirmation="signature",
    )
    config["origin"]["phone"] = ""  # Quotes do not require full purchase readiness.
    config["package"] = dict(
        id=order["packages"][0]["id"],
        weight_g=1,
        length_mm=1,
        width_mm=1,
        height_mm=1,
        us_units=dict(weight_oz=17.1, length_in=8.1, width_in=7, height_in=6),
    )
    return order, config, {"x-csrf-token": client.app.state.csrf_token}


def install(client, handler=fake_response, test_mode=False):
    adapter = ShipStationTestProvider if test_mode else ShipStationProvider
    provider = adapter("mock-key", "mock-secret", True, httpx.MockTransport(handler))
    provider.catalog = catalog
    client.app.state.providers[provider.code] = provider
    return provider


@pytest.mark.parametrize("live_enabled", [False, True])
def test_rates_read_only_sort_selectable_codes_and_same_measurements(tmp_path, live_enabled):
    with TestClient(
        create_app(Settings(data_dir=tmp_path, enable_live_purchase=live_enabled))
    ) as client:
        order, config, headers = configured(client)
        calls = []

        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            assert body["weight"] == {"value": 18, "units": "ounces"}
            assert body["dimensions"] == {"length": 9, "width": 7, "height": 6, "units": "inches"}
            assert body["residential"] is True
            assert body["confirmation"] == "signature"
            assert body["serviceCode"] is None and body["packageCode"] == "package"
            return fake_response(request)

        install(client, handler, test_mode=not live_enabled)
        response = client.post(f"/api/orders/{order['id']}/rates", json=config, headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert {c["carrierCode"] for c in calls} == {"stamps_com", "ups", "fedex"}
        assert len(calls) == 3
        assert [r["total_minor"] for r in result["rates"]] == [858] * 3 + [2210] * 3
        assert result["partial"] is False
        assert all(r["package_code"] == "package" for r in result["rates"])
        assert client.get("/api/orders/" + order["id"]).json() == order
        with client.app.state.engine.connect() as db:
            assert db.execute(text("SELECT count(*) FROM label_attempts")).scalar() == 0
        assert "mock-secret" not in response.text
        config["version"] += 1
        assert (
            client.post(
                f"/api/orders/{order['id']}/rates", json=config, headers=headers
            ).status_code
            == 409
        )
        assert len(calls) == 3


def test_partial_errors_no_fake_zero_and_specific_package(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, enable_live_purchase=True))) as client:
        order, config, headers = configured(client)

        def handler(request):
            body = json.loads(request.content)
            if body["carrierCode"] == "ups":
                return httpx.Response(500, text="PRIVATE TOKEN MUST NOT LEAK")
            if body["carrierCode"] == "fedex":
                return httpx.Response(
                    200,
                    json=[{"serviceCode": "fedex_ground", "shipmentCost": None, "otherCost": 0}],
                )
            return fake_response(request)

        provider = install(client, handler)
        url = f"/api/orders/{order['id']}/rates"
        result = client.post(url, json=config, headers=headers).json()
        assert result["partial"] and len(result["warnings"]) == 2
        assert len(result["rates"]) == 2 and result["rates"][0]["total_minor"] == 858
        assert "PRIVATE" not in str(result)
        config.update(scope="selected")
        config["shipping"].update(carrier_code="stamps_com", package_code="flat_rate_box")
        result = client.post(url, json=config, headers=headers).json()
        assert len(result["rates"]) == 2
        assert all(r["package_code"] == "flat_rate_box" for r in result["rates"])
        with provider.rate_query_lock:
            assert client.post(url, json=config, headers=headers).status_code == 429
        config["package"]["id"] = "wrong-order-package"
        assert client.post(url, json=config, headers=headers).status_code == 422


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_rate_adapter_errors_redacted_and_never_purchase(status):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, text="SECRET RESPONSE")

    provider = ShipStationProvider("key", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderUnavailable) as exc:
        provider.get_rates({})
    assert "SECRET" not in str(exc.value)
    assert calls == ["/shipments/getrates"]
    if status == 429:
        with pytest.raises(ProviderUnavailable):
            provider.get_rates({})
        assert len(calls) == 1
    provider.close()


def test_unsupported_package_and_missing_confirmation_do_not_request_rates(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, enable_live_purchase=True))) as client:
        order, config, headers = configured(client)

        def no_network(_):
            raise AssertionError("No remote request expected")

        provider = install(client, no_network)
        custom = catalog()
        for carrier in custom["carriers"]:
            carrier["packages"] = [{"code": "flat_rate_box", "name": "Flat rate"}]
        provider.catalog = lambda: custom
        url = f"/api/orders/{order['id']}/rates"
        result = client.post(url, json=config, headers=headers).json()
        assert not result["rates"] and len(result["warnings"]) == 3
        config["shipping"]["confirmation"] = ""
        assert client.post(url, json=config, headers=headers).status_code == 422


def test_canada_payload_no_customs_or_insurance_promised():
    from tests.test_shipstation import snapshot

    order = snapshot()
    order["shipping"].update(carrier_code="fedex", package_code="package", insurance="none")
    purchase = build_payload(order)
    rates = rate_payload(order, "fedex", "package")
    assert rates["toCountry"] == "CA"
    assert rates["dimensions"] == purchase["dimensions"]
    assert rates["weight"] == purchase["weight"]
    assert not {"insuranceOptions", "internationalOptions", "testLabel"} & rates.keys()
