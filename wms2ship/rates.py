"""Read-only rate shopping against the same primary accounts used for label purchase."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from wms2ship.configuration import OrderConfiguration, validate_order
from wms2ship.orders import load_order
from wms2ship.shipstation import ProviderUnavailable, package_fields

router = APIRouter()


class RateRequest(OrderConfiguration):
    scope: Literal["standard", "selected"] = "standard"


def rate_payload(order, carrier_code, package_code):
    # Use the purchase conversion so rounding and dimensions agree exactly.
    origin, recipient = order["origin"], order["recipient"]
    return {
        "carrierCode": carrier_code,
        "serviceCode": None,
        "packageCode": package_code,
        "fromPostalCode": origin["postal"],
        "fromCity": origin["city"],
        "fromState": origin["state"],
        "toCountry": recipient["country"],
        "toPostalCode": recipient["postal"],
        "toState": recipient["state"],
        "toCity": recipient["city"],
        **package_fields(order["packages"][0]),
        "residential": order["shipping"]["residential"],
        "confirmation": order["shipping"]["confirmation"],
    }


def cents(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral():
            raise ValueError()
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError(
            "Incomplete or invalid prices returned; no quote shown for this carrier."
        ) from None


def carrier_quotes(provider, order, carrier, package):
    code = carrier["code"]
    try:
        rows = provider.get_rates(rate_payload(order, code, package["code"]))
        scope = "international" if order["recipient"]["country"] == "CA" else "domestic"
        services = {s["code"]: s for s in carrier["services"] if s.get(scope) is not False}
        quotes = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid rate response.")
            if not isinstance(row.get("serviceCode"), str):
                raise ValueError("Invalid service code in rate response.")
            service = services.get(row.get("serviceCode"))
            if service is None:
                raise ValueError(
                    "Returned services do not match available purchase services. Refresh and retry."
                )
            shipment, other = cents(row.get("shipmentCost")), cents(row.get("otherCost"))
            quotes.append(
                {
                    "carrier_code": code,
                    "carrier_name": carrier["name"],
                    "service_code": service["code"],
                    "service_name": service["name"],
                    "package_code": package["code"],
                    "package_name": package["name"],
                    "shipment_minor": shipment,
                    "other_minor": other,
                    "total_minor": shipment + other,
                    "currency": "USD",
                }
            )
        if not quotes:
            return [], f"{carrier['name']}: No services available for these shipment details."
        return quotes, None
    except (ProviderUnavailable, ValueError) as exc:
        return [], f"{carrier['name']}: {exc}"


@router.post("/api/orders/{order_id}/rates")
def compare_rates(order_id: str, payload: RateRequest, request: Request):
    with request.app.state.engine.connect() as db:
        order = load_order(db, order_id)
    if order["version"] != payload.version:
        raise HTTPException(409, "Order changed; reopen it before comparing rates.")
    values = payload.model_dump(mode="json")
    provider_code = (
        "shipstation" if request.app.state.settings.enable_live_purchase else "shipstation_test"
    )
    provider = request.app.state.providers.get(provider_code)
    if provider is None:
        raise HTTPException(400, "Connect ShipStation in Settings to compare real rates.")
    values["shipping"]["provider"] = provider_code
    order.update({key: values[key] for key in ("origin", "shipping", "customs")})
    if payload.package is not None:
        package = next((p for p in order["packages"] if p["id"] == payload.package.id), None)
        if package is None:
            raise HTTPException(422, "Package does not belong to this order.")
        package.update(payload.package.storage_values())
    # Rates need shipment details, but not a preselected carrier/service or customs declaration.
    ignored = {
        "origin.name",
        "origin.phone",
        "origin.address1",
        "shipping.carrier_code",
        "shipping.service_code",
        "shipping.package_code",
        "shipping.provider",
        "shipping.insurance",
        "shipping.insured_value",
        "shipping.duties_payer",
    }
    issues = [
        i
        for i in validate_order(order, {"provider": provider_code, "carriers": []})
        if i["field"] not in ignored
        and not i["field"].startswith("customs.")
        and not (
            i["field"] == "shipping.confirmation"
            and order["shipping"]["confirmation"] == "direct_signature"
        )
    ]
    if issues:
        raise HTTPException(422, {"issues": issues})
    if not provider.rate_query_lock.acquire(blocking=False):
        raise HTTPException(429, "Another rate comparison is running. Try again shortly.")
    try:
        catalog = provider.catalog()
        warnings, candidates = [], []
        shipping = order["shipping"]
        destination = "international" if order["recipient"]["country"] == "CA" else "domestic"
        for carrier in catalog["carriers"]:
            if provider_code == "shipstation_test" and carrier["code"] != "stamps_com":
                continue
            if payload.scope == "selected" and carrier["code"] != shipping["carrier_code"]:
                continue
            if shipping["confirmation"] == "direct_signature" and not carrier["code"].startswith(
                "fedex"
            ):
                warnings.append(f"{carrier['name']}: Direct signature is only available for FedEx.")
                continue
            package_code = shipping["package_code"] if payload.scope == "selected" else "package"
            package = next(
                (
                    p
                    for p in carrier["packages"]
                    if p["code"] == package_code and p.get(destination) is not False
                ),
                None,
            )
            if package is None:
                warnings.append(
                    f"{carrier['name']}: No compatible package type. "
                    "Choose a package and use selected carrier/package comparison."
                )
                continue
            candidates.append((carrier, package))
        if len(candidates) > 12:
            raise HTTPException(
                422, "Too many connected carriers. Compare the selected carrier/package instead."
            )
        if not candidates and not warnings:
            warnings.append(
                "Choose an available carrier and package, or use standard parcel comparison."
            )
        quotes = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            tasks = [pool.submit(carrier_quotes, provider, order, c, p) for c, p in candidates]
            for task in tasks:
                found, warning = task.result()
                quotes.extend(found)
                if warning:
                    warnings.append(warning)
        quotes.sort(key=lambda q: (q["total_minor"], q["carrier_name"], q["service_name"]))
        return {
            "rates": quotes,
            "warnings": warnings,
            "partial": bool(warnings),
            "quoted_at": datetime.now(timezone.utc).isoformat(),
            "valid_for_seconds": 300,
            "mode": provider.mode,
            "note": "Estimate in USD: shipment cost plus returned other charges. "
            "Insurance, selected add-ons, duties/taxes and later adjustments are not included. "
            "Ship date pricing and delivery estimates are not provided by this endpoint. "
            "Actual charge is recorded after purchase.",
        }
    finally:
        provider.rate_query_lock.release()
