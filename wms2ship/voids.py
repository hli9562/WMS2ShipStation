"""Manual local label removal; never sends a request to the carrier."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import text

from wms2ship.configuration import DraftModel
from wms2ship.purchases import event, now

router = APIRouter()


class VoidRequest(DraftModel):
    confirm_void: bool = False


class VoidResolution(DraftModel):
    outcome: Literal["voided", "not_voided"]
    evidence: str = Field(min_length=20, max_length=2000)


def label_record(db, label_id):
    row = (
        db.execute(
            text(
                "SELECT l.*,p.provider_code FROM labels l "
                "JOIN label_attempts a ON a.id=l.attempt_id "
                "JOIN provider_accounts p ON p.id=a.provider_account_id WHERE l.id=:id"
            ),
            {"id": label_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, "Label not found.")
    return row


def finish(db, row, status, kind, evidence=None):
    db.execute(
        text("UPDATE labels SET void_status=:status,void_updated_at=:time WHERE id=:id"),
        dict(status=status, time=now(), id=row["id"]),
    )
    if status == "voided":
        db.execute(
            text("DELETE FROM purchase_guards WHERE package_id=:package AND attempt_id=:attempt"),
            dict(package=row["package_id"], attempt=row["attempt_id"]),
        )
    event(db, row["attempt_id"], kind, {"label_id": row["id"], **(evidence or {})})


@router.post("/api/labels/{label_id}/void")
def void_label(label_id: str, payload: VoidRequest, request: Request):
    if not payload.confirm_void:
        raise HTTPException(400, "Explicit confirmation is required to remove a label.")
    engine = request.app.state.engine
    with engine.connect() as db:
        db.exec_driver_sql("BEGIN IMMEDIATE")
        row = label_record(db, label_id)
        if row["void_status"] == "voided":
            return {"label_id": label_id, "void_status": "voided"}
        finish(db, row, "voided", "label_removed_locally")
        db.commit()
    return {"label_id": label_id, "void_status": "voided"}


@router.post("/api/labels/{label_id}/void/resolve")
def resolve_void(label_id: str, payload: VoidResolution, request: Request):
    if len(payload.evidence.strip()) < 20:
        raise HTTPException(422, "Supply evidence from manual provider verification.")
    with request.app.state.engine.connect() as db:
        db.exec_driver_sql("BEGIN IMMEDIATE")
        row = label_record(db, label_id)
        # Pending may still be executing. Interrupted requests become uncertain on startup.
        if row["void_status"] != "uncertain":
            raise HTTPException(409, "Only uncertain voids can be resolved manually.")
        status = "voided" if payload.outcome == "voided" else "active"
        finish(
            db,
            row,
            status,
            "void_manually_resolved",
            {"outcome": payload.outcome, "evidence": payload.evidence.strip()},
        )
        db.commit()
    return {"label_id": label_id, "void_status": status}


def recover_interrupted_voids(engine):
    with engine.begin() as db:
        rows = db.execute(text("SELECT * FROM labels WHERE void_status='pending'")).mappings().all()
        for row in rows:
            finish(db, row, "uncertain", "void_interrupted")
