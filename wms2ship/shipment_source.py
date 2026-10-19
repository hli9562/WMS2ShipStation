"""Read-only ShipStation account shipments, independent of label purchasing."""

from copy import deepcopy
from datetime import date
from threading import Lock
from time import monotonic

import httpx

from wms2ship.shipstation import ProviderUnavailable


class ShipmentSource:
    def __init__(self, key, secret, transport=None):
        self.client = httpx.Client(
            base_url="https://ssapi.shipstation.com",
            auth=httpx.BasicAuth(key, secret),
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.lock = Lock()
        self.cache = {}
        self.blocked_until = 0

    def close(self):
        self.client.close()

    def shipments(self, start: date, end: date):
        key = (start.isoformat(), end.isoformat())
        with self.lock:
            cached = self.cache.get(key)
            if cached and monotonic() - cached[0] < 60:
                return deepcopy(cached[1])
            if monotonic() < self.blocked_until:
                raise ProviderUnavailable(
                    "ShipStation rate limit reached. Wait one minute and retry."
                )
            rows = {}
            expected = None
            for page in range(1, 101):
                try:
                    response = self.client.get(
                        "/shipments",
                        params={
                            "shipDateStart": key[0],
                            "shipDateEnd": key[1],
                            "sortBy": "CreateDate",
                            "sortDir": "ASC",
                            "includeShipmentItems": "false",
                            "pageSize": 100,
                            "page": page,
                        },
                    )
                except httpx.HTTPError:
                    raise ProviderUnavailable(
                        "Cannot read ShipStation shipments. Check the connection and retry. "
                        "No fee total was calculated."
                    ) from None
                if response.status_code in (401, 403):
                    raise ProviderUnavailable(
                        f"ShipStation shipments access denied (HTTP {response.status_code}). "
                        "Check that the V1 API Key and API Secret are active, "
                        "and that this account has V1 API access. "
                        "No fee total was calculated."
                    )
                if response.status_code == 429:
                    self.blocked_until = monotonic() + 60
                    raise ProviderUnavailable(
                        "ShipStation rate limit reached. Wait one minute and retry. "
                        "No partial fee total was calculated."
                    )
                if not response.is_success:
                    raise ProviderUnavailable(
                        f"ShipStation shipments returned HTTP {response.status_code}. "
                        "Retry shortly. No partial fee total was calculated."
                    )
                try:
                    body = response.json()
                    batch = body["shipments"]
                    total = int(body["total"])
                    if not isinstance(batch, list) or total < 0:
                        raise ValueError()
                    if total > 10000:
                        raise ProviderUnavailable(
                            "ShipStation limits shipment pagination to 10,000 results. "
                            "Select a shorter date range; no partial total was calculated."
                        )
                    if expected is not None and total != expected:
                        raise ProviderUnavailable(
                            "ShipStation shipments changed during loading. Retry the report "
                            "to calculate a complete total."
                        )
                    expected = total
                    for row in batch:
                        if not isinstance(row, dict) or row.get("shipmentId") is None:
                            raise ValueError()
                        rows[str(row["shipmentId"])] = row
                except (KeyError, TypeError, ValueError):
                    raise ProviderUnavailable(
                        "ShipStation returned an invalid shipment response. "
                        "No fee total was calculated."
                    ) from None
                if len(rows) == expected:
                    result = list(rows.values())
                    if len(self.cache) >= 8:
                        self.cache.pop(next(iter(self.cache)))
                    self.cache[key] = (monotonic(), deepcopy(result))
                    return result
                if not batch or len(rows) > expected:
                    break
            raise ProviderUnavailable(
                "ShipStation returned an incomplete shipment list. "
                "Retry or select a shorter range; no partial total was calculated."
            )
