import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from wms2ship.import_routes import order_detail

router = APIRouter()


class DraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Origin(DraftModel):
    name: str = Field(default="", max_length=100)
    company: str = Field(default="", max_length=100)
    phone: str = Field(default="", max_length=40)
    address1: str = Field(default="", max_length=200)
    address2: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=100)
    state: str = Field(default="", max_length=2)
    postal: str = Field(default="", max_length=20)
    country: str = Field(default="", max_length=2)

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country(cls, value):
        if not isinstance(value, str):
            return value
        code = value.strip().upper()
        return {
            "UNITED STATES": "US",
            "UNITED STATES OF AMERICA": "US",
            "USA": "US",
            "U.S.": "US",
            "U.S.A.": "US",
            "CANADA": "CA",
        }.get(code, code)

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, value):
        if not isinstance(value, str):
            return value
        code = value.strip().upper()
        return "TX" if code == "TEXAS" else code


class Shipping(DraftModel):
    provider: Literal["fake", "shipstation", "shipstation_test"] = "fake"
    carrier_code: str = Field(default="", max_length=100)
    service_code: str = Field(default="", max_length=100)
    package_code: str = Field(default="", max_length=100)
    ship_date: date | None = None
    timezone: str = Field(default="", max_length=100)
    residential: bool | None = None
    confirmation: Literal[
        "", "none", "delivery", "signature", "adult_signature", "direct_signature"
    ] = ""
    insurance: Literal[
        "", "none", "carrier", "shipsurance", "provider", "xcover", "parcelguard"
    ] = ""
    saturday_delivery: bool = False
    non_machinable: bool = False
    contains_alcohol: bool = False
    insured_value: str = Field(default="", max_length=30)
    duties_payer: Literal["", "recipient"] = ""


class Declaration(DraftModel):
    item_id: str
    description: str = Field(default="", max_length=200)
    quantity: int = Field(ge=1)
    unit_value: str = Field(default="", max_length=30)
    currency: str = Field(default="", max_length=3)
    country_of_origin: str = Field(default="", max_length=2)
    hs_code: str = Field(default="", max_length=15)


class Customs(DraftModel):
    contents: Literal["", "merchandise", "documents", "gift", "returned_goods", "sample"] = ""
    non_delivery: Literal["", "return_to_sender", "treat_as_abandoned"] = ""
    items: list[Declaration] = Field(default_factory=list, max_length=100)


class OrderConfiguration(DraftModel):
    version: int = Field(ge=1)
    origin: Origin
    shipping: Shipping
    customs: Customs | None = None


# Explicit simulated choices; never passed to a live shipping provider.
FAKE_CHOICES = {
    "mode": "simulation",
    "carriers": [
        {
            "code": "demo",
            "name": "Demo carrier — simulated, no postage",
            "services": [{"code": "demo_ground", "name": "Demo ground — simulated"}],
            "packages": [{"code": "demo_parcel", "name": "Demo parcel — simulated"}],
        }
    ],
}


def positive_money(value):
    try:
        amount = Decimal(value)
        return amount.is_finite() and amount > 0 and amount.as_tuple().exponent >= -2
    except (InvalidOperation, TypeError):
        return False


def validate_order(order, catalog):
    issues = []

    def issue(field, message):
        issues.append({"field": field, "message": message})

    origin = order.get("origin") or {}
    shipping = order.get("shipping") or {}
    recipient = order.get("recipient") or {}
    for field in ("name", "phone", "address1", "city", "state", "postal", "country"):
        if not origin.get(field):
            issue(f"origin.{field}", "Required warehouse/contact information.")
    if (
        origin.get("country", "").upper() != "US"
        or origin.get("state", "").upper() != "TX"
        or origin.get("city", "").casefold() != "katy"
    ):
        issue("origin", "Use the Katy, TX, US warehouse; return address is the same.")
    if origin.get("postal") and not re.fullmatch(r"\d{5}(-\d{4})?", origin["postal"]):
        issue("origin.postal", "Use a US ZIP code.")
    if recipient.get("country") not in {"US", "CA"}:
        issue("recipient.country", "Only US and Canada are supported.")
    for field in ("name", "address1", "city", "state", "postal"):
        if not recipient.get(field):
            issue(f"recipient.{field}", "Required recipient information is missing.")
    if len(order["packages"]) != 1:
        issue("packages", "Exactly one unambiguous package is supported.")
    for package in order["packages"]:
        for field in ("length_mm", "width_mm", "height_mm", "weight_g"):
            if not package.get(field) or package[field] <= 0:
                issue(f"packages.{field}", "A positive measurement is required.")
        if package.get("source_tracking"):
            issue(
                "packages.source_tracking",
                "Existing WMS tracking requires investigation; purchase blocked.",
            )
    if shipping.get("provider") == "shipstation_test":
        if shipping.get("carrier_code") != "stamps_com":
            issue("shipping.carrier_code", "ShipStation V1 test labels require Stamps.com (USPS).")
        if shipping.get("insurance") != "none" or any(
            shipping.get(key) for key in ("saturday_delivery", "non_machinable", "contains_alcohol")
        ):
            issue("shipping", "USPS test labels require no insurance or shipping add-ons.")
    if shipping.get("provider") != catalog.get("provider", "fake"):
        issue(
            "shipping.provider",
            "The configured provider does not match the selected shipping catalog.",
        )
    carriers = catalog.get("carriers", [])
    selected = next((c for c in carriers if c["code"] == shipping.get("carrier_code")), None)
    if selected is None:
        issue("shipping.carrier_code", "Choose an available carrier.")
    else:
        for field, options in (("service_code", "services"), ("package_code", "packages")):
            choice = next((c for c in selected[options] if c["code"] == shipping.get(field)), None)
            if choice is None:
                issue(f"shipping.{field}", "Choose an available option for the selected carrier.")
            elif (
                choice.get("international" if recipient.get("country") == "CA" else "domestic")
                is False
            ):
                issue(f"shipping.{field}", "Option does not support this destination scope.")
    if not shipping.get("ship_date"):
        issue("shipping.ship_date", "Choose a ship date.")
    if shipping.get("residential") is None:
        issue("shipping.residential", "Choose residential or commercial.")
    if (
        shipping.get("provider") in {"shipstation", "shipstation_test"}
        and shipping.get("confirmation") == "direct_signature"
        and not shipping.get("carrier_code", "").startswith("fedex")
    ):
        issue("shipping.confirmation", "Direct signature is available for FedEx only.")
    if not shipping.get("confirmation"):
        issue("shipping.confirmation", "Choose a delivery confirmation option, including none.")
    if not shipping.get("insurance"):
        issue("shipping.insurance", "Choose an insurance option, including none.")
    elif shipping["insurance"] != "none" and not positive_money(shipping.get("insured_value")):
        issue(
            "shipping.insured_value",
            "Enter a positive insured value with at most two decimal places.",
        )
    if recipient.get("country") == "CA":
        if shipping.get("duties_payer") != "recipient":
            issue(
                "shipping.duties_payer",
                "Choose recipient-paid duties; other billing modes are not yet supported.",
            )
        customs = order.get("customs") or {}
        for field in ("contents", "non_delivery"):
            if not customs.get(field):
                issue(f"customs.{field}", "Required for Canadian shipments.")
        declarations = customs.get("items", [])
        expected = {item["id"]: item["quantity"] for item in order["items"]}
        actual = {item.get("item_id"): item.get("quantity") for item in declarations}
        if not expected or expected != actual or len(actual) != len(declarations):
            issue("customs.items", "Declare each item exactly once, using the imported quantities.")
        for index, item in enumerate(declarations):
            prefix = f"customs.items.{index}"
            if not item.get("description"):
                issue(f"{prefix}.description", "Enter a customs description.")
            if not positive_money(item.get("unit_value")):
                issue(
                    f"{prefix}.unit_value",
                    "Enter a positive unit value with at most two decimal places.",
                )
            # V1 CustomsItem does not carry currency; only USD supported initially.
            if item.get("currency") != "USD":
                issue(
                    f"{prefix}.currency",
                    "This V1 integration currently requires USD customs values.",
                )
            if not re.fullmatch(r"[A-Z]{2}", item.get("country_of_origin", "")):
                issue(f"{prefix}.country_of_origin", "Enter a two-letter origin country code.")
            if not re.fullmatch(r"\d{6,10}", item.get("hs_code", "")):
                issue(f"{prefix}.hs_code", "Enter the 6–10 digit HS code without punctuation.")
    return issues


@router.get("/api/providers/{provider}/carriers")
def catalog(provider: str, request: Request):
    adapter = request.app.state.providers.get(provider)
    if adapter is None:
        raise HTTPException(400, "Provider is not configured.")
    return adapter.catalog()


@router.patch("/api/orders/{order_id}")
def configure(order_id: str, payload: OrderConfiguration, request: Request):
    values = payload.model_dump(mode="json")
    if request.app.state.settings.shipstation_api_key.get_secret_value():
        values["shipping"]["provider"] = "shipstation_test"
    origin = values["origin"]
    # Only the Katy warehouse is supported; never trust a manually supplied timezone.
    values["shipping"]["timezone"] = (
        "America/Chicago"
        if origin["country"] == "US"
        and origin["state"] == "TX"
        and origin["city"].casefold() == "katy"
        else ""
    )
    with request.app.state.engine.begin() as db:
        result = db.execute(
            text(
                "UPDATE orders SET origin_json=:origin,shipping_json=:shipping,"
                "customs_json=:customs,"
                "version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=:id AND version=:version"
            ),
            {
                "origin": json.dumps(values["origin"]),
                "shipping": json.dumps(values["shipping"]),
                "customs": json.dumps(values["customs"]) if values["customs"] else None,
                "id": order_id,
                "version": payload.version,
            },
        )
        if result.rowcount != 1:
            exists = db.execute(
                text("SELECT 1 FROM orders WHERE id=:id"), {"id": order_id}
            ).scalar()
            raise HTTPException(
                409 if exists else 404,
                "Order changed; reload before saving." if exists else "Order not found.",
            )
    return order_detail(order_id, request)


@router.post("/api/orders/{order_id}/validate")
def validate(order_id: str, request: Request):
    order = order_detail(order_id, request)
    provider = request.app.state.providers.get(
        (order.get("shipping") or {}).get("provider", "fake")
    )
    if provider is None:
        raise HTTPException(400, "Provider is not configured.")
    issues = validate_order(order, provider.catalog())
    return {
        "valid": not issues,
        "issues": issues,
        "mode": provider.mode,
        "version": order["version"],
    }


@router.post("/api/orders/{order_id}/readiness")
def draft_readiness(order_id: str, payload: OrderConfiguration, request: Request):
    order = order_detail(order_id, request)
    if order["version"] != payload.version:
        raise HTTPException(409, "Order changed; reload before continuing.")
    values = payload.model_dump(mode="json")
    if request.app.state.settings.shipstation_api_key.get_secret_value():
        values["shipping"]["provider"] = "shipstation_test"
    order.update({key: values[key] for key in ("origin", "shipping", "customs")})
    provider = request.app.state.providers.get(values["shipping"]["provider"])
    if provider is None:
        raise HTTPException(400, "Provider is not configured.")
    issues = validate_order(order, provider.catalog())
    return {"valid": not issues, "issues": issues, "mode": provider.mode}
