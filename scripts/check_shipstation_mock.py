"""Probe ShipStation's documentation mock using synthetic data and dummy credentials.

Run from the repository: uv run python -m scripts.check_shipstation_mock
Never reads application settings, connects to production, or saves purchase history.
"""

import base64
import binascii
import json
from datetime import date

import httpx

from wms2ship.shipstation import build_payload

MOCK_BASE = "https://docs.shipstation.com/_mock/apis/shipstation-v1/openapi"


def synthetic_payload():
    warehouse = {
        "name": "Synthetic Test",
        "address1": "100 Synthetic Street",
        "city": "Katy",
        "state": "TX",
        "postal": "77494",
        "country": "US",
        "phone": "+15555550100",
    }
    payload = build_payload(
        {
            "origin": warehouse,
            "recipient": warehouse,
            "packages": [{"weight_g": 460, "length_mm": 200, "width_mm": 185, "height_mm": 140}],
            "shipping": {
                "carrier_code": "fedex",
                "service_code": "fedex_ground",
                "package_code": "package",
                "ship_date": date.today().isoformat(),
                "confirmation": "none",
                "insurance": "none",
                "residential": False,
            },
        }
    )
    payload["testLabel"] = True
    return payload


def main():
    report = {"server": MOCK_BASE, "mode": "documentation_mock", "checks": [], "limitations": []}
    try:
        # Fixed documentation origin; no redirects or production credentials.
        with httpx.Client(
            base_url=MOCK_BASE,
            auth=("mock-user", "mock-password"),
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for path in (
                "/stores",
                "/carriers",
                "/carriers/listservices?carrierCode=fedex",
                "/carriers/listpackages?carrierCode=fedex",
            ):
                response = client.get(path)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError(f"Unexpected response shape: {path}")
                report["checks"].append(
                    {"path": path, "status": response.status_code, "rows": len(data)}
                )
                if path == "/stores" and not any(
                    store.get("active") is True and store.get("marketplaceId") == 0
                    for store in data
                ):
                    report["limitations"].append("Mock store example has no active Manual Store.")
                if "listpackages" in path and any(p.get("carrierCode") != "fedex" for p in data):
                    report["limitations"].append(
                        "Mock package example does not match requested carrier."
                    )
            response = client.post("/shipments/createlabel", json=synthetic_payload())
            response.raise_for_status()
            data = response.json()
            report["checks"].append(
                {
                    "path": "/shipments/createlabel",
                    "status": response.status_code,
                    "has_shipment_id": "shipmentId" in data,
                    "has_tracking": bool(data.get("trackingNumber")),
                }
            )
            try:
                pdf = base64.b64decode(data.get("labelData", ""), validate=True)
                printable = pdf.startswith(b"%PDF-") and b"%%EOF" in pdf
            except (binascii.Error, TypeError):
                printable = False
            report["label_pdf_candidate"] = printable
            if not printable:
                report["limitations"].append("Mock labelData is a placeholder, not a complete PDF.")
            invalid = client.post("/shipments/createlabel", json={})
            report["empty_request_status"] = invalid.status_code
            if invalid.is_success:
                report["limitations"].append(
                    "Mock accepts an empty label request; it does not validate required fields."
                )
    except (httpx.HTTPError, ValueError) as error:
        # Dummy credentials and synthetic data only; report type rather than HTTP body.
        report["error"] = type(error).__name__
        print(json.dumps(report, indent=2))
        return 1
    report["note"] = "Mock tracking and labels are not valid postage. No production API was called."
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
