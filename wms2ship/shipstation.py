"""ShipStation V1 adapter. Fixed HTTPS origin; no automatic purchase retries."""

import base64
import binascii
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic

import httpx

from wms2ship.providers import PurchaseRejected, PurchaseResult, PurchaseUncertain


class ProviderUnavailable(Exception):
    pass


class LookupCache:
    """Short-lived, account-local read cache shared by paid and test providers."""

    def __init__(self):
        self.lock = Lock()
        self.responses = {}
        self.blocked_until = 0
        self.blocked_message = ""


def address(value, residential=False):
    return {
        "name": value["name"],
        "company": value.get("company") or None,
        "street1": value["address1"],
        "street2": value.get("address2") or None,
        "city": value["city"],
        "state": value["state"].upper(),
        "postalCode": value["postal"],
        "country": value["country"].upper(),
        "phone": value.get("phone") or None,
        "residential": residential,
    }


def build_payload(snapshot):
    shipping = snapshot["shipping"]
    package = snapshot["packages"][0]
    payload = {
        "carrierCode": shipping["carrier_code"],
        "serviceCode": shipping["service_code"],
        "packageCode": shipping["package_code"],
        "shipDate": shipping["ship_date"],
        "confirmation": shipping["confirmation"],
        "weight": {"value": package["weight_g"], "units": "grams"},
        "dimensions": {
            "units": "centimeters",
            **{key: package[f"{key}_mm"] / 10 for key in ("length", "width", "height")},
        },
        "shipFrom": address(snapshot["origin"]),
        "shipTo": address(snapshot["recipient"], shipping["residential"]),
        "testLabel": False,
    }
    advanced = {
        remote: shipping.get(local, False)
        for local, remote in (
            ("saturday_delivery", "saturdayDelivery"),
            ("non_machinable", "nonMachinable"),
            ("contains_alcohol", "containsAlcohol"),
        )
    }
    if any(advanced.values()):
        payload["advancedOptions"] = advanced
    if shipping["insurance"] != "none":
        payload["insuranceOptions"] = {
            "provider": shipping["insurance"],
            "insureShipment": True,
            "insuredValue": float(Decimal(shipping["insured_value"])),
        }
    if snapshot["recipient"]["country"] == "CA":
        customs = snapshot["customs"]
        payload["internationalOptions"] = {
            "contents": customs["contents"],
            "nonDelivery": customs["non_delivery"],
            "customsItems": [
                {
                    "description": item["description"],
                    "quantity": item["quantity"],
                    "value": float(Decimal(item["unit_value"])),
                    "harmonizedTariffCode": item["hs_code"],
                    "countryOfOrigin": item["country_of_origin"],
                }
                for item in customs["items"]
            ],
        }
    # WMS/platform references stay local: order-only advanced fields are not assumed
    # to work for standalone shipment labels, nor used as remote idempotency keys.
    return payload


class ShipStationProvider:
    code = "shipstation"
    mode = "live"
    allowed_carrier_codes = None

    def __init__(self, key, secret, enable_live=False, transport=None, lookup_cache=None):
        self.enable_live = enable_live
        self.lookup_cache = lookup_cache if lookup_cache is not None else LookupCache()
        self.client = httpx.Client(
            base_url="https://ssapi.shipstation.com",
            auth=httpx.BasicAuth(key, secret),
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        )

    def close(self):
        self.client.close()

    def get(self, path, params=None):
        key = (path, tuple(sorted((params or {}).items())))
        cache = self.lookup_cache
        # Coalesce concurrent form refreshes; label POSTs never use this cache.
        with cache.lock:
            cached = cache.responses.get(key)
            if cached and monotonic() - cached[0] < 300:
                return deepcopy(cached[1])
            if monotonic() < cache.blocked_until:
                raise ProviderUnavailable(cache.blocked_message)
            try:
                response = self.client.get(path, params=params)
            except httpx.TimeoutException:
                raise ProviderUnavailable(
                    f"ShipStation {path} timed out. Try again shortly."
                ) from None
            except httpx.HTTPError:
                raise ProviderUnavailable(
                    f"Cannot connect to ShipStation {path}. Check the network and try again."
                ) from None
            if response.status_code == 429:
                try:
                    wait = max(1, min(3600, int(response.headers.get("X-Rate-Limit-Reset", "60"))))
                except ValueError:
                    wait = 60
                cache.blocked_until = monotonic() + wait
                cache.blocked_message = (
                    f"ShipStation rate limit reached (HTTP 429). Wait {wait} seconds, "
                    "then reopen the order."
                )
                raise ProviderUnavailable(cache.blocked_message)
            if response.status_code in (401, 403):
                raise ProviderUnavailable(
                    f"ShipStation denied access to {path} (HTTP {response.status_code}). "
                    "Check the V1 credentials and API permissions."
                )
            if not response.is_success:
                raise ProviderUnavailable(
                    f"ShipStation {path} returned HTTP {response.status_code}. Try again shortly."
                )
            try:
                result = response.json()
                if not isinstance(result, list):
                    raise ValueError()
            except ValueError:
                raise ProviderUnavailable(
                    f"ShipStation {path} returned an invalid lookup response. Try again shortly."
                ) from None
            cache.responses[key] = (monotonic(), deepcopy(result))
            return result

    def catalog(self):
        stores = self.get("/stores", {"showInactive": "false"})
        if not any(s.get("marketplaceId") == 0 and s.get("active") is True for s in stores):
            raise ProviderUnavailable("An active ShipStation Manual Store is required.")
        accounts = self.get("/carriers")
        grouped = {}
        for account in accounts:
            grouped.setdefault(account["code"], []).append(account)
        carriers = []
        for code, accounts in grouped.items():
            if self.allowed_carrier_codes is not None and code not in self.allowed_carrier_codes:
                continue
            # Direct-label flow initially supports the primary connected carrier account.
            selected = next((a for a in accounts if a.get("primary") is True), None)
            if selected is None and len(accounts) == 1:
                selected = accounts[0]
            if selected is None:
                continue
            services = self.get("/carriers/listservices", {"carrierCode": code})
            packages = self.get("/carriers/listpackages", {"carrierCode": code})
            carriers.append(
                {
                    "code": code,
                    "name": selected["name"] + " (primary account)",
                    "services": [
                        {k: s[k] for k in ("code", "name", "domestic", "international") if k in s}
                        for s in services
                    ],
                    "packages": [
                        {k: p[k] for k in ("code", "name", "domestic", "international") if k in p}
                        for p in packages
                    ],
                }
            )
        return {
            "provider": self.code,
            "mode": self.mode,
            "carriers": carriers,
            "live_purchase_enabled": self.enable_live,
        }

    def create_label(self, snapshot, attempt_id):
        if not self.enable_live:
            raise PurchaseRejected("Live purchasing is disabled.")
        return self._submit_payload(build_payload(snapshot))

    def _submit_payload(self, body):
        try:
            response = self.client.post("/shipments/createlabel", json=body)
        except httpx.HTTPError:
            raise PurchaseUncertain() from None
        # Only unambiguous authorization/validation rejection codes release guards.
        # 408, 429, 5xx, redirects and malformed success bodies remain uncertain.
        if response.status_code in {400, 401, 403, 404, 405, 422}:
            raise PurchaseRejected()
        if not response.is_success:
            raise PurchaseUncertain()
        try:
            data = response.json()
            shipment = str(data["shipmentId"])
            tracking = str(data["trackingNumber"])
            if (
                not shipment
                or not tracking
                or data["shipmentId"] is None
                or data["trackingNumber"] is None
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise PurchaseUncertain() from None
        # Known purchase identity survives missing/corrupt PDF or charge metadata.
        pdf = None
        try:
            decoded = base64.b64decode(data.get("labelData", ""), validate=True)
            if decoded.startswith(b"%PDF-"):
                pdf = decoded
        except (binascii.Error, TypeError):
            pass
        charge = None
        try:
            amount = Decimal(str(data["shipmentCost"])) + Decimal(str(data.get("insuranceCost", 0)))
            if (
                amount.is_finite()
                and amount >= 0
                and amount * 100 == (amount * 100).to_integral_value()
            ):
                charge = int(amount * 100)
        except (InvalidOperation, KeyError, TypeError):
            pass
        return PurchaseResult(
            shipment, None, tracking, pdf, charge, "USD" if charge is not None else None
        )


class ShipStationTestProvider(ShipStationProvider):
    """USPS-only test labels; cannot send a paid-label payload."""

    code = "shipstation_test"
    mode = "test"
    def create_label(self, snapshot, attempt_id):
        shipping = snapshot["shipping"]
        if (
            shipping.get("carrier_code") != "stamps_com"
            or shipping.get("insurance") != "none"
            or any(
                shipping.get(key)
                for key in ("saturday_delivery", "non_machinable", "contains_alcohol")
            )
        ):
            raise PurchaseRejected("Use USPS test mode without insurance or add-ons.")
        body = build_payload(snapshot)
        body["testLabel"] = True
        return self._submit_payload(body)
