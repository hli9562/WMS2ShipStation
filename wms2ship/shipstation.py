"""ShipStation V1 adapter. Fixed HTTPS origin; no automatic purchase retries."""

import base64
import binascii
from decimal import Decimal, InvalidOperation

import httpx

from wms2ship.providers import PurchaseRejected, PurchaseResult, PurchaseUncertain


class ProviderUnavailable(Exception):
    pass


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

    def __init__(self, key, secret, enable_live=False, transport=None):
        self.enable_live = enable_live
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
        try:
            response = self.client.get(path, params=params)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, list):
                raise ValueError()
            return result
        except (httpx.HTTPError, ValueError):
            raise ProviderUnavailable(
                "ShipStation lookup failed. Check account access and try again."
            ) from None

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
        body = build_payload(snapshot)
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
