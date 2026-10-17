"""Run INSIDE a disposable CI app container. Creates synthetic simulation data only."""

import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date
from uuid import uuid4

from pypdf import PdfReader

from wms2ship.sample import sample_workbook

BASE = os.getenv("WMS_SMOKE_BASE_URL", "http://127.0.0.1:8080")
home = urllib.request.urlopen(BASE).read().decode()
csrf = re.search(r'name="csrf-token" content="([^"]+)"', home)[1]


def api(path, body=None, method=None, expect=200, raw=False):
    data = body if raw else json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    try:
        response = urllib.request.urlopen(request)
    except urllib.error.HTTPError as error:
        response = error
    assert response.status == expect, (path, response.status, response.read())
    payload = response.read()
    return payload if "pdf" in response.headers.get("content-type", "") else json.loads(payload)


start = time.perf_counter()
prefix = f"CI-{uuid4()}"
workbook = sample_workbook("US", 99, prefix)
result = api("/api/imports?filename=ci.xlsx", workbook, "POST", 201, True)
assert result["created"] == 99
assert api("/api/imports?filename=repeat.xlsx", workbook, "POST", 201, True)["duplicates"] == 99
print(f"99 synthetic orders imported and re-imported in {time.perf_counter() - start:.2f}s")
order_id = next(o["id"] for o in api("/api/orders") if o["wms_order_no"] == prefix + "-001")
order = api(f"/api/orders/{order_id}")
config = {
    "version": order["version"],
    "origin": {
        "name": "Synthetic Warehouse",
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
        "insurance": "none",
        "confirmation": "none",
    },
    "customs": None,
}
order = api(f"/api/orders/{order_id}", config, "PATCH")
assert api(f"/api/orders/{order_id}/validate", {}, "POST")["valid"]
payload = {
    "version": order["version"],
    "package_id": order["packages"][0]["id"],
    "request_token": str(uuid4()),
    "confirm_purchase": True,
}
attempt = api(f"/api/orders/{order_id}/label-attempts", payload, "POST")
assert attempt["state"] == "purchased" and attempt["mode"] == "simulation"
assert api(f"/api/orders/{order_id}/label-attempts", payload, "POST")["id"] == attempt["id"]
payload["request_token"] = str(uuid4())
api(f"/api/orders/{order_id}/label-attempts", payload, "POST", expect=409)
label = attempt["labels"][0]["id"]
for _ in range(2):
    pdf = api(f"/api/labels/{label}/pdf")
    assert tuple(PdfReader(io.BytesIO(pdf)).pages[0].mediabox) == (0, 0, 612, 792)
assert any(row["label_id"] == label for row in api("/api/history"))
print("PASS: import, configure, simulated purchase, duplicate protection, history and reprint")
