import hashlib
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pypdf import PdfReader, PdfWriter, Transformation
from sqlalchemy import text

from wms2ship.providers import provider_mode
from wms2ship.purchases import event, now, store_pdf

router = APIRouter()


def letter_pdf(original):
    reader = PdfReader(io.BytesIO(original), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
        raise ValueError("Use an unencrypted PDF with 1–20 pages.")
    writer = PdfWriter()
    source_writer = PdfWriter(clone_from=reader)
    for page in source_writer.pages:
        if float(page.get("/UserUnit", 1)) != 1:
            raise ValueError("Unsupported PDF unit scale; use the original label.")
        page.transfer_rotation_to_content()
        width = float(page.cropbox.width)
        height = float(page.cropbox.height)
        if width > 612 and height <= 612 and width <= 792:
            page.rotate(90)
            page.transfer_rotation_to_content()
            width, height = float(page.cropbox.width), float(page.cropbox.height)
        if width <= 0 or height <= 0 or width > 612.01 or height > 792.01:
            raise ValueError(
                "Original page does not fit Letter without scaling; use original and review layout."
            )
        output = writer.add_blank_page(width=612, height=792)
        transform = Transformation().translate(
            tx=(612 - width) / 2 - float(page.cropbox.left),
            ty=(792 - height) / 2 - float(page.cropbox.bottom),
        )
        output.merge_transformed_page(page, transform)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def artifact(engine, label_id, kind):
    with engine.connect() as db:
        return (
            db.execute(
                text("SELECT * FROM label_artifacts WHERE label_id=:id AND kind=:kind"),
                {"id": label_id, "kind": kind},
            )
            .mappings()
            .first()
        )


def read_artifact(settings, row):
    if row is None:
        raise HTTPException(
            409, "Stored label is missing; recover the existing purchase, do not buy again."
        )
    key = row["storage_key"]
    if Path(key).name != key:
        raise HTTPException(409, "Invalid artifact storage reference.")
    try:
        data = (settings.labels_dir / key).read_bytes()
    except OSError:
        raise HTTPException(
            409, "Label file is missing; restore backup or recover the existing purchase."
        ) from None
    if len(data) != row["byte_count"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise HTTPException(
            409, "Label checksum mismatch; restore or recover the existing purchase."
        )
    return data


@router.get("/api/labels/{label_id}/pdf")
def label_pdf(
    label_id: str, request: Request, kind: str = Query("original", pattern="^(original|letter)$")
):
    engine = request.app.state.engine
    settings = request.app.state.settings
    with engine.connect() as db:
        status = db.execute(
            text("SELECT void_status FROM labels WHERE id=:id"), {"id": label_id}
        ).scalar()
        if status is None:
            raise HTTPException(404, "Label not found.")
        if status in ("pending", "uncertain", "voided"):
            raise HTTPException(409, "This label is voided or its void outcome needs verification.")
    row = artifact(engine, label_id, kind)
    if row is not None:
        data = read_artifact(settings, row)
    else:
        data = read_artifact(settings, artifact(engine, label_id, "original"))
        if kind == "letter":
            try:
                data = letter_pdf(data)
            except Exception:
                raise HTTPException(
                    422,
                    "PDF cannot be composed safely on Letter without scaling. "
                    "Download the original and review its layout.",
                ) from None
            key, checksum = store_pdf(settings, f"{label_id}.letter", data)
            with engine.begin() as db:
                db.execute(
                    text(
                        "INSERT INTO label_artifacts "
                        "(id,label_id,kind,storage_key,sha256,byte_count,created_at) VALUES "
                        "(:id,:label,'letter',:key,:sha,:size,:time) "
                        "ON CONFLICT(label_id,kind) DO NOTHING"
                    ),
                    {
                        "id": f"{label_id}-letter",
                        "label": label_id,
                        "key": key,
                        "sha": checksum,
                        "size": len(data),
                        "time": now(),
                    },
                )
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="label-{label_id}-{kind}.pdf"'},
    )


@router.get("/api/history")
def history(
    request: Request,
    order_id: str | None = None,
    search: str = Query("", max_length=200),
    start: datetime | None = None,
    end: datetime | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    for value in (start, end):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(422, "History times must include a timezone.")
    if start and end and start > end:
        raise HTTPException(422, "Start time must be on or before end time.")
    clauses = []
    params = {"order": order_id, "limit": limit, "offset": offset}
    if order_id:
        clauses.append("a.order_id=:order")
    if start:
        clauses.append("julianday(a.created_at)>=julianday(:start)")
        params["start"] = start.isoformat()
    if end:
        clauses.append("julianday(a.created_at)<=julianday(:end)")
        params["end"] = end.isoformat()
    if search.strip():
        value = search.strip()
        pattern = "".join(
            {"!": "!!", "%": "!%", "_": "!_", "*": "%", "?": "_"}.get(c, c) for c in value
        )
        if not any(c in value for c in "*?"):
            pattern = "%" + pattern + "%"
        params["search"] = pattern
        fields = [
            "o.wms_order_no",
            "o.platform_reference",
            "l.tracking_number",
            "a.id",
            "l.id",
            "a.state",
            "a.error_code",
            "p.provider_code",
            "CASE p.provider_code WHEN 'fake' THEN 'simulation' "
            "WHEN 'shipstation_test' THEN 'test' ELSE 'live' END",
        ]
        clauses.append(
            "(" + " OR ".join(f"COALESCE({f},'') LIKE :search ESCAPE '!'" for f in fields) + ")"
        )
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with request.app.state.engine.connect() as db:
        rows = (
            db.execute(
                text(
                    "SELECT a.id AS attempt_id,CASE WHEN l.void_status='voided' "
                    "THEN 'removed' ELSE a.state END AS state,"
                    "a.state AS purchase_state,a.error_code,a.created_at,o.id AS order_id,"
                    "o.wms_order_no,p.provider_code,l.id AS label_id,l.tracking_number,"
                    "l.provider_shipment_id,l.void_status,l.void_updated_at,"
                    "l.charge_minor,l.currency FROM label_attempts a "
                    "JOIN orders o ON o.id=a.order_id "
                    "JOIN provider_accounts p ON p.id=a.provider_account_id "
                    "LEFT JOIN labels l ON l.attempt_id=a.id "
                    + where
                    + " ORDER BY a.created_at DESC,a.id LIMIT :limit OFFSET :offset"
                ),
                params,
            )
            .mappings()
            .all()
        )
        return [{**dict(row), "mode": provider_mode(row["provider_code"])} for row in rows]


@router.post("/api/labels/{label_id}/recover")
async def recover_label(label_id: str, request: Request):
    evidence = request.headers.get("x-recovery-evidence", "")
    if not 20 <= len(evidence) <= 2000:
        raise HTTPException(
            422, "Supply evidence identifying the existing provider label (20–2000 characters)."
        )
    settings = request.app.state.settings
    engine = request.app.state.engine
    with engine.connect() as db:
        label = (
            db.execute(
                text(
                    "SELECT l.attempt_id,a.state FROM labels l "
                    "JOIN label_attempts a ON a.id=l.attempt_id WHERE l.id=:id"
                ),
                {"id": label_id},
            )
            .mappings()
            .first()
        )
    if not label or label["state"] != "purchased":
        raise HTTPException(409, "Only a confirmed purchase can have its PDF recovered.")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, "PDF exceeds upload limit.")
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
            raise ValueError()
    except Exception:
        raise HTTPException(422, "Supply a valid unencrypted PDF with 1–20 pages.") from None
    existing = artifact(engine, label_id, "original")
    checksum = hashlib.sha256(data).hexdigest()
    if existing and existing["sha256"] != checksum:
        raise HTTPException(409, "Recovery PDF differs from the previously stored original.")
    key, checksum = store_pdf(settings, label_id, bytes(data))
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO label_artifacts "
                "(id,label_id,kind,storage_key,sha256,byte_count,created_at) "
                "VALUES(:id,:label,'original',:key,:sha,:size,:time) "
                "ON CONFLICT(label_id,kind) DO NOTHING"
            ),
            {
                "id": f"{label_id}-recovered",
                "label": label_id,
                "key": key,
                "sha": checksum,
                "size": len(data),
                "time": now(),
            },
        )
        db.execute(
            text("UPDATE label_attempts SET error_code=NULL WHERE id=:id"),
            {"id": label["attempt_id"]},
        )
        event(db, label["attempt_id"], "artifact_recovered", {"evidence": evidence})
    return {"label_id": label_id, "status": "recovered"}
