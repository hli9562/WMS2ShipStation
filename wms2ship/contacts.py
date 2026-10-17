"""Reusable contacts; orders retain independent copies of selected addresses."""

import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import text

from wms2ship.configuration import DraftModel, Origin

router = APIRouter(prefix="/api/shipper-contacts")


class Contact(DraftModel):
    label: str = Field(min_length=1, max_length=100)
    address: Origin


@router.get("")
def list_contacts(request: Request):
    with request.app.state.engine.connect() as db:
        rows = db.execute(text("SELECT * FROM shipper_contacts ORDER BY label, id")).mappings()
        return [
            dict(id=r["id"], label=r["label"], address=json.loads(r["address_json"])) for r in rows
        ]


@router.post("", status_code=201)
def create_contact(payload: Contact, request: Request):
    contact_id = str(uuid4())
    with request.app.state.engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO shipper_contacts (id,label,address_json) VALUES (:id,:label,:address)"
            ),
            {
                "id": contact_id,
                "label": payload.label,
                "address": payload.address.model_dump_json(),
            },
        )
    return {"id": contact_id, **payload.model_dump()}


@router.put("/{contact_id}")
def update_contact(contact_id: str, payload: Contact, request: Request):
    with request.app.state.engine.begin() as db:
        result = db.execute(
            text("UPDATE shipper_contacts SET label=:label,address_json=:address WHERE id=:id"),
            {
                "id": contact_id,
                "label": payload.label,
                "address": payload.address.model_dump_json(),
            },
        )
        if result.rowcount != 1:
            raise HTTPException(404, "Contact not found.")
    return {"id": contact_id, **payload.model_dump()}


@router.delete("/{contact_id}")
def delete_contact(contact_id: str, request: Request):
    with request.app.state.engine.begin() as db:
        result = db.execute(text("DELETE FROM shipper_contacts WHERE id=:id"), {"id": contact_id})
        if result.rowcount != 1:
            raise HTTPException(404, "Contact not found.")
    return {"deleted": True}
