"""Workspace configuration; credentials are never returned to the browser."""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from wms2ship.providers import FakeProvider
from wms2ship.shipment_source import ShipmentSource
from wms2ship.shipstation import ShipStationProvider, ShipStationTestProvider

router = APIRouter(prefix="/api/settings")


class ShippingDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    carrier_code: str = Field(default="", max_length=100)
    service_code: str = Field(default="", max_length=100)
    package_code: str = Field(default="", max_length=100)
    confirmation: Literal[
        "none", "delivery", "signature", "adult_signature", "direct_signature"
    ] = "delivery"
    residential: bool = True
    insurance: Literal["none", "carrier"] = "none"


class PackageTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    length_in: float = Field(gt=0, le=10000, allow_inf_nan=False)
    width_in: float = Field(gt=0, le=10000, allow_inf_nan=False)
    height_in: float = Field(gt=0, le=10000, allow_inf_nan=False)

    @field_validator("length_in", "width_in", "height_in")
    @classmethod
    def whole_inches(cls, value):
        return math.ceil(value)


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = SecretStr("")
    api_secret: SecretStr = SecretStr("")


def credential_path(settings):
    return settings.data_dir / "shipstation_credentials.json"


def saved_credentials(settings):
    path = credential_path(settings)
    if not path.exists():
        return (
            settings.shipstation_api_key.get_secret_value(),
            settings.shipstation_api_secret.get_secret_value(),
        )
    try:
        data = json.loads(path.read_text())
        key, secret = data["api_key"], data["api_secret"]
        if not isinstance(key, str) or not isinstance(secret, str) or not key or not secret:
            raise ValueError()
        return key, secret
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError("Saved ShipStation configuration cannot be read.") from None


def install_connections(app, key, secret):
    providers = {"fake": app.state.providers.get("fake") or FakeProvider()}
    source = None
    if key and secret:
        live = ShipStationProvider(key, secret, app.state.settings.enable_live_purchase)
        providers.update(
            shipstation=live,
            shipstation_test=ShipStationTestProvider(key, secret, lookup_cache=live.lookup_cache),
        )
        source = ShipmentSource(key, secret)
    # In-flight requests retain usable clients. Close retired clients at shutdown.
    app.state.retired_connections.extend(
        p for p in app.state.providers.values() if hasattr(p, "close")
    )
    if app.state.shipment_source:
        app.state.retired_connections.append(app.state.shipment_source)
    app.state.providers = providers
    app.state.shipment_source = source
    app.state.settings.shipstation_api_key = SecretStr(key)
    app.state.settings.shipstation_api_secret = SecretStr(secret)


def verify_credentials(key, secret, transport=None):
    result = dict(connected=False, checked_at=datetime.now(timezone.utc).isoformat())
    if not key or not secret:
        return {**result, "message": "Enter both V1 API Key and API Secret."}
    try:
        with httpx.Client(
            base_url="https://ssapi.shipstation.com",
            auth=(key, secret),
            timeout=httpx.Timeout(20, connect=10),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        ) as client:
            for endpoint in ("/carriers", "/shipments?page=1&pageSize=1"):
                response = client.get(endpoint)
                if not response.is_success:
                    return {
                        **result,
                        "status_code": response.status_code,
                        "message": f"ShipStation returned HTTP {response.status_code}. "
                        "Check active V1 credentials and account API access.",
                    }
                try:
                    data = response.json()
                    valid = (
                        isinstance(data, list)
                        if endpoint == "/carriers"
                        else (isinstance(data, dict) and isinstance(data.get("shipments"), list))
                    )
                    if not valid:
                        raise ValueError()
                except ValueError:
                    return {
                        **result,
                        "message": "ShipStation returned an unexpected response. "
                        "Connection could not be verified.",
                    }
        return {
            **result,
            "connected": True,
            "message": "Connected: carrier and account shipment access verified.",
        }
    except httpx.HTTPError:
        return {**result, "message": "Cannot reach ShipStation. Check the network and retry."}


def templates(engine):
    with engine.connect() as db:
        return [
            dict(row)
            for row in db.execute(
                text("SELECT * FROM package_templates ORDER BY name,id")
            ).mappings()
        ]


@router.get("")
def workspace_settings(request: Request):
    app = request.app
    with app.state.engine.connect() as db:
        value = db.execute(
            text("SELECT value_json FROM workspace_preferences WHERE id='shipping_defaults'")
        ).scalar()
    return dict(
        shipping_defaults=json.loads(value) if value else ShippingDefaults().model_dump(),
        package_templates=templates(app.state.engine),
        connection=dict(
            configured=app.state.shipment_source is not None,
            live_purchase_enabled=app.state.settings.enable_live_purchase,
            last_test=app.state.connection_status,
        ),
    )


@router.put("/shipping-defaults")
def save_defaults(payload: ShippingDefaults, request: Request):
    with request.app.state.engine.begin() as db:
        db.execute(
            text("""INSERT INTO workspace_preferences (id,value_json)
            VALUES ('shipping_defaults',:value)
            ON CONFLICT(id) DO UPDATE SET value_json=excluded.value_json"""),
            {"value": payload.model_dump_json()},
        )
    return workspace_settings(request)


@router.post("/package-templates", status_code=201)
@router.put("/package-templates/{template_id}")
def save_template(payload: PackageTemplate, request: Request, template_id: str | None = None):
    identity = template_id or str(uuid4())
    try:
        with request.app.state.engine.begin() as db:
            if template_id:
                result = db.execute(
                    text("""UPDATE package_templates SET name=:name,
                    length_in=:length_in,width_in=:width_in,height_in=:height_in WHERE id=:id"""),
                    {**payload.model_dump(), "id": identity},
                )
                if result.rowcount != 1:
                    raise HTTPException(404, "Package template not found.")
            else:
                db.execute(
                    text("""INSERT INTO package_templates
                    (id,name,length_in,width_in,height_in)
                    VALUES (:id,:name,:length_in,:width_in,:height_in)"""),
                    {**payload.model_dump(), "id": identity},
                )
    except IntegrityError:
        raise HTTPException(409, "A package template with this name already exists.") from None
    return workspace_settings(request)


@router.delete("/package-templates/{template_id}")
def delete_template(template_id: str, request: Request):
    with request.app.state.engine.begin() as db:
        result = db.execute(text("DELETE FROM package_templates WHERE id=:id"), {"id": template_id})
        if result.rowcount != 1:
            raise HTTPException(404, "Package template not found.")
    return workspace_settings(request)


def credential_values(payload, request):
    key, secret = (
        payload.api_key.get_secret_value().strip(),
        payload.api_secret.get_secret_value().strip(),
    )
    if not key and not secret:
        settings = request.app.state.settings
        return (
            settings.shipstation_api_key.get_secret_value(),
            settings.shipstation_api_secret.get_secret_value(),
        )
    if (
        not key
        or not secret
        or max(len(key), len(secret)) > 500
        or any(ord(c) < 33 or ord(c) > 126 for c in key + secret)
    ):
        raise HTTPException(422, "Enter both valid V1 API Key and API Secret.")
    return key, secret


@router.post("/shipstation/test")
def test_connection(payload: Credentials, request: Request):
    key, secret = credential_values(payload, request)
    result = verify_credentials(key, secret)
    if not payload.api_key.get_secret_value() and not payload.api_secret.get_secret_value():
        request.app.state.connection_status = result
    return result


@router.put("/shipstation")
def save_connection(payload: Credentials, request: Request):
    if (
        not payload.api_key.get_secret_value().strip()
        or not payload.api_secret.get_secret_value().strip()
    ):
        raise HTTPException(
            422, "Enter both new credentials to save. Blank fields keep existing values."
        )
    key, secret = credential_values(payload, request)
    app = request.app
    with app.state.settings_lock:
        result = verify_credentials(key, secret)
        if not result["connected"]:
            raise HTTPException(422, result["message"])
        path = credential_path(app.state.settings)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as output:
                json.dump({"api_key": key, "api_secret": secret}, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        install_connections(app, key, secret)
        app.state.connection_status = result
    return workspace_settings(request)


def initialize_workspace(app):
    app.state.settings_lock = Lock()
    app.state.retired_connections = []
    app.state.connection_status = None
    app.state.providers = {}
    app.state.shipment_source = None
    install_connections(app, *saved_credentials(app.state.settings))
