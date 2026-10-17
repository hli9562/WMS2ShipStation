import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from wms2ship.configuration import DraftModel, validate_order
from wms2ship.providers import PurchaseRejected

router = APIRouter()


def now():
    return datetime.now(UTC).isoformat()


def load_order(db, order_id):
    row = db.execute(text("SELECT * FROM orders WHERE id=:id"), {"id": order_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Order not found.")
    result = dict(row)
    for field in ("recipient", "origin", "shipping", "customs"):
        result[field] = json.loads(result.pop(f"{field}_json") or "null")
    result["packages"] = [
        dict(p)
        for p in db.execute(
            text("SELECT * FROM packages WHERE order_id=:id"), {"id": order_id}
        ).mappings()
    ]
    result["items"] = [
        dict(p)
        for p in db.execute(
            text("SELECT * FROM order_items WHERE order_id=:id"), {"id": order_id}
        ).mappings()
    ]
    return result


def event(db, attempt_id, kind, evidence=None):
    db.execute(
        text("INSERT INTO attempt_events VALUES(:id,:attempt,'local',:kind,:evidence,:time)"),
        {
            "id": str(uuid4()),
            "attempt": attempt_id,
            "kind": kind,
            "evidence": json.dumps(evidence or {}),
            "time": now(),
        },
    )


def attempt_detail(engine, attempt_id):
    with engine.connect() as db:
        row = (
            db.execute(
                text(
                    "SELECT a.id,a.order_id,a.order_version,a.state,a.error_code,"
                    "a.created_at,a.updated_at,p.provider_code FROM label_attempts a "
                    "JOIN provider_accounts p ON p.id=a.provider_account_id WHERE a.id=:id"
                ),
                {"id": attempt_id},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Attempt not found.")
        result = dict(row)
        result["mode"] = "simulation" if row["provider_code"] == "fake" else "live"
        result["labels"] = [
            dict(label)
            for label in db.execute(
                text(
                    "SELECT id,tracking_number,provider_shipment_id,provider_label_id,"
                    "charge_minor,currency "
                    "FROM labels WHERE attempt_id=:id"
                ),
                {"id": attempt_id},
            ).mappings()
        ]
        result["events"] = [
            dict(e)
            for e in db.execute(
                text(
                    "SELECT event_type,evidence_json,created_at FROM attempt_events "
                    "WHERE attempt_id=:id ORDER BY created_at"
                ),
                {"id": attempt_id},
            ).mappings()
        ]
        return result


class CreateAttempt(DraftModel):
    version: int = Field(ge=1)
    package_id: str
    request_token: str = Field(min_length=16, max_length=100)
    confirm_purchase: bool = False


def reserve(engine, order_id, payload, provider, catalog):
    attempt_id = str(uuid4())
    with engine.connect() as db:
        db.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            existing = (
                db.execute(
                    text(
                        "SELECT id,order_id,order_version FROM label_attempts "
                        "WHERE request_token=:token"
                    ),
                    {"token": payload.request_token},
                )
                .mappings()
                .first()
            )
            if existing:
                membership = db.execute(
                    text("SELECT package_id FROM attempt_packages WHERE attempt_id=:id"),
                    {"id": existing["id"]},
                ).scalar_one()
                if (
                    existing["order_id"] != order_id
                    or existing["order_version"] != payload.version
                    or membership != payload.package_id
                ):
                    raise HTTPException(
                        409, "Request token was already used for a different purchase."
                    )
                db.rollback()
                return existing["id"], None
            snapshot = load_order(db, order_id)
            if snapshot["version"] != payload.version:
                raise HTTPException(409, "Order changed; reload and review before purchasing.")
            if (snapshot.get("shipping") or {}).get("provider") != provider.code:
                raise HTTPException(409, "Configured provider does not match this request.")
            issues = validate_order(snapshot, catalog)
            if issues:
                raise HTTPException(422, {"message": "Shipment is not ready.", "issues": issues})
            if [p["id"] for p in snapshot["packages"]] != [payload.package_id]:
                raise HTTPException(422, "Selected package does not belong to this order.")
            provider_id = provider.code
            db.execute(
                text(
                    "INSERT INTO provider_accounts "
                    "(id,provider_code,display_name,credential_reference,enabled) "
                    "VALUES(:id,:id,:id,:ref,1) ON CONFLICT(id) DO NOTHING"
                ),
                {"id": provider_id, "ref": "server-environment"},
            )
            db.execute(
                text(
                    "INSERT INTO label_attempts "
                    "(id,order_id,provider_account_id,order_version,request_token,state,"
                    "request_snapshot_json,actor_id,created_at,updated_at) VALUES "
                    "(:id,:order,:provider,:version,:token,'prepared',:snapshot,'local',:time,:time)"
                ),
                {
                    "id": attempt_id,
                    "order": order_id,
                    "provider": provider_id,
                    "version": payload.version,
                    "token": payload.request_token,
                    "snapshot": json.dumps(snapshot),
                    "time": now(),
                },
            )
            db.execute(
                text("INSERT INTO attempt_packages VALUES(:id,:package)"),
                {"id": attempt_id, "package": payload.package_id},
            )
            db.execute(
                text("INSERT INTO purchase_guards VALUES(:package,:id,:time)"),
                {"package": payload.package_id, "id": attempt_id, "time": now()},
            )
            event(db, attempt_id, "prepared", {"mode": provider.mode})
            db.commit()
            return attempt_id, snapshot
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                409, "This package already has a purchase or unresolved attempt."
            ) from None
        except Exception:
            db.rollback()
            raise


def store_pdf(settings, label_id, payload):
    if not payload.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF data.")
    target = settings.labels_dir / f"{label_id}.pdf"
    descriptor, temp_path = tempfile.mkstemp(dir=settings.labels_dir, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
    finally:
        Path(temp_path).unlink(missing_ok=True)
    return target.name, hashlib.sha256(payload).hexdigest()


def finish_purchase(engine, settings, attempt_id, snapshot, result):
    label_id = str(uuid4())
    evidence = {
        "shipment_id": result.shipment_id,
        "label_id": result.label_id,
        "tracking": result.tracking,
        "charge_minor": result.charge_minor,
        "currency": result.currency,
    }
    # Commit purchase identity before trying to store artifacts.
    with engine.begin() as db:
        db.execute(
            text(
                "UPDATE label_attempts SET state='purchased',provider_evidence_json=:e,"
                "updated_at=:time WHERE id=:id"
            ),
            {"e": json.dumps(evidence), "time": now(), "id": attempt_id},
        )
        db.execute(
            text(
                "INSERT INTO labels VALUES(:id,:attempt,:package,:shipment,:label,:tracking,"
                ":charge,:currency,:time)"
            ),
            {
                "id": label_id,
                "attempt": attempt_id,
                "package": snapshot["packages"][0]["id"],
                "shipment": result.shipment_id,
                "label": result.label_id,
                "tracking": result.tracking,
                "charge": result.charge_minor,
                "currency": result.currency,
                "time": now(),
            },
        )
        event(db, attempt_id, "purchased", evidence)
    try:
        if not result.pdf:
            raise ValueError("No PDF returned.")
        key, checksum = store_pdf(settings, label_id, result.pdf)
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO label_artifacts "
                    "VALUES(:id,:label,'original',:key,:sha,:size,:time)"
                ),
                {
                    "id": str(uuid4()),
                    "label": label_id,
                    "key": key,
                    "sha": checksum,
                    "size": len(result.pdf),
                    "time": now(),
                },
            )
            event(db, attempt_id, "artifact_saved")
    except Exception:
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE label_attempts SET error_code='artifact_recovery_required' WHERE id=:id"
                ),
                {"id": attempt_id},
            )
            event(db, attempt_id, "artifact_recovery_required")


def purchase(engine, settings, order_id, payload, provider):
    catalog = provider.catalog()
    attempt_id, snapshot = reserve(engine, order_id, payload, provider, catalog)
    if snapshot is None:
        return attempt_detail(engine, attempt_id)
    with engine.begin() as db:
        db.execute(
            text("UPDATE label_attempts SET state='sending',updated_at=:time WHERE id=:id"),
            {"id": attempt_id, "time": now()},
        )
        event(db, attempt_id, "sending")
    try:
        result = provider.create_label(snapshot, attempt_id)
    except PurchaseRejected:
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE label_attempts SET state='failed',error_code='provider_rejected',"
                    "updated_at=:time WHERE id=:id"
                ),
                {"id": attempt_id, "time": now()},
            )
            db.execute(text("DELETE FROM purchase_guards WHERE attempt_id=:id"), {"id": attempt_id})
            event(db, attempt_id, "confirmed_rejection")
    except Exception:
        # Deliberately do not persist/log exception text: it may contain secrets or addresses.
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE label_attempts SET state='uncertain',error_code='reconcile_required',"
                    "updated_at=:time WHERE id=:id"
                ),
                {"id": attempt_id, "time": now()},
            )
            event(db, attempt_id, "outcome_uncertain")
    else:
        finish_purchase(engine, settings, attempt_id, snapshot, result)
    return attempt_detail(engine, attempt_id)


def recover_interrupted(engine):
    with engine.begin() as db:
        rows = (
            db.execute(text("SELECT id FROM label_attempts WHERE state IN ('prepared','sending')"))
            .scalars()
            .all()
        )
        for attempt_id in rows:
            db.execute(
                text(
                    "UPDATE label_attempts SET state='uncertain',error_code='interrupted',"
                    "updated_at=:time WHERE id=:id"
                ),
                {"id": attempt_id, "time": now()},
            )
            event(db, attempt_id, "restart_reconciliation_required")


@router.post("/api/orders/{order_id}/label-attempts")
def create_label_attempt(order_id: str, payload: CreateAttempt, request: Request):
    if not payload.confirm_purchase:
        raise HTTPException(400, "Explicit confirmation is required to create a label.")
    with request.app.state.engine.connect() as db:
        order = load_order(db, order_id)
    code = (order.get("shipping") or {}).get("provider", "fake")
    provider = request.app.state.providers.get(code)
    if provider is None:
        raise HTTPException(400, "Provider is not available.")
    if provider.mode == "live" and not provider.enable_live:
        raise HTTPException(400, "Live purchase is disabled in server configuration.")
    return purchase(
        request.app.state.engine, request.app.state.settings, order_id, payload, provider
    )


@router.get("/api/label-attempts/{attempt_id}")
def get_attempt(attempt_id: str, request: Request):
    return attempt_detail(request.app.state.engine, attempt_id)


class Reconciliation(BaseModel):
    outcome: str = Field(pattern="^(confirmed_not_purchased|purchased)$")
    evidence: str = Field(min_length=20, max_length=2000)
    shipment_id: str | None = None
    tracking: str | None = None


@router.post("/api/label-attempts/{attempt_id}/reconcile")
def reconcile(attempt_id: str, payload: Reconciliation, request: Request):
    engine = request.app.state.engine
    with engine.connect() as db:
        db.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            row = (
                db.execute(text("SELECT * FROM label_attempts WHERE id=:id"), {"id": attempt_id})
                .mappings()
                .first()
            )
            if not row:
                raise HTTPException(404, "Attempt not found.")
            if row["state"] != "uncertain":
                raise HTTPException(409, "Only unresolved attempts may be reconciled.")
            if payload.outcome == "confirmed_not_purchased":
                db.execute(
                    text(
                        "UPDATE label_attempts SET state='failed',error_code=NULL,"
                        "updated_at=:time WHERE id=:id"
                    ),
                    {"id": attempt_id, "time": now()},
                )
                db.execute(
                    text("DELETE FROM purchase_guards WHERE attempt_id=:id"), {"id": attempt_id}
                )
            else:
                if not payload.shipment_id or not payload.tracking:
                    raise HTTPException(
                        422, "Provide the confirmed shipment ID and tracking number."
                    )
                package_id = db.execute(
                    text("SELECT package_id FROM attempt_packages WHERE attempt_id=:id"),
                    {"id": attempt_id},
                ).scalar_one()
                db.execute(
                    text(
                        "INSERT INTO labels (id,attempt_id,package_id,provider_shipment_id,"
                        "tracking_number,created_at) "
                        "VALUES(:label,:id,:package,:shipment,:tracking,:time)"
                    ),
                    {
                        "label": str(uuid4()),
                        "id": attempt_id,
                        "package": package_id,
                        "shipment": payload.shipment_id,
                        "tracking": payload.tracking,
                        "time": now(),
                    },
                )
                db.execute(
                    text(
                        "UPDATE label_attempts SET state='purchased',"
                        "error_code='artifact_recovery_required',updated_at=:time WHERE id=:id"
                    ),
                    {"id": attempt_id, "time": now()},
                )
            event(db, attempt_id, "operator_reconciliation", payload.model_dump())
            db.commit()
        except Exception:
            db.rollback()
            raise
    return attempt_detail(engine, attempt_id)
