import json
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from starlette.concurrency import run_in_threadpool

from wms2ship.importer import ImportRejected, import_workbook
from wms2ship.orders import load_order
from wms2ship.ship_dates import default_ship_date

router = APIRouter()


@router.post("/api/imports", status_code=201)
async def upload(request: Request, filename: str):
    filename = PurePosixPath(filename.replace("\\", "/")).name
    if not filename.lower().endswith(".xlsx") or len(filename) > 240:
        raise HTTPException(400, "Choose an .xlsx file with a filename under 240 characters.")
    limit = request.app.state.settings.max_upload_bytes
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, "File exceeds the upload size limit.")
        chunks.append(chunk)
    try:
        return await run_in_threadpool(
            import_workbook,
            request.app.state.engine,
            b"".join(chunks),
            filename,
            request.app.state.settings,
        )
    except ImportRejected as exc:
        raise HTTPException(422, str(exc)) from None


class ImportFingerprints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hashes: list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]] = Field(max_length=200)


@router.post("/api/imports/check")
def check_imported(payload: ImportFingerprints, request: Request):
    hashes = list(dict.fromkeys(payload.hashes))
    if not hashes:
        return {"files": []}
    with request.app.state.engine.connect() as db:
        rows = (
            db.execute(
                text(
                    "SELECT id,sha256,summary_json FROM import_batches WHERE sha256 IN :hashes "
                    "ORDER BY created_at DESC,id DESC"
                ).bindparams(bindparam("hashes", expanding=True)),
                {"hashes": hashes},
            )
            .mappings()
            .all()
        )
    latest = {}
    for row in rows:
        if row["sha256"] not in latest:
            summary = json.loads(row["summary_json"])
            latest[row["sha256"]] = {
                "sha256": row["sha256"],
                "batch_id": row["id"],
                "summary": summary,
                "status": "needs_review" if summary.get("invalid", 0) else "imported",
            }
    return {"files": [latest.get(h, {"sha256": h, "status": "new"}) for h in hashes]}


@router.get("/api/imports/{batch_id}")
def import_detail(batch_id: str, request: Request):
    with request.app.state.engine.connect() as db:
        batch = (
            db.execute(text("SELECT * FROM import_batches WHERE id=:id"), {"id": batch_id})
            .mappings()
            .first()
        )
        if not batch:
            raise HTTPException(404, "Import not found.")
        rows = (
            db.execute(
                text(
                    "SELECT sheet_name,row_number,source_order_no,order_id,"
                    "issues_json,evidence_json "
                    "FROM import_rows WHERE batch_id=:id ORDER BY sheet_name,row_number"
                ),
                {"id": batch_id},
            )
            .mappings()
            .all()
        )
        return {
            "id": batch_id,
            "filename": batch["original_filename"],
            "summary": json.loads(batch["summary_json"]),
            "rows": [
                {
                    "sheet": row["sheet_name"],
                    "row": row["row_number"],
                    "source_order_no": row["source_order_no"],
                    "order_id": row["order_id"],
                    "issues": json.loads(row["issues_json"]),
                    "evidence": json.loads(row["evidence_json"]),
                }
                for row in rows
            ],
        }


@router.get("/api/orders")
def orders(
    request: Request,
    search: str = Query("", max_length=200),
    status: str = Query("all", pattern="^(all|new|purchased|removed|attention)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=1000),
):
    query = """
        WITH listed AS (
          SELECT o.id,o.wms_order_no,o.platform_reference,o.created_at,
            json_extract(o.recipient_json, '$.name') AS recipient_name,
            CASE WHEN l.void_status='voided' THEN 'removed' ELSE a.state END AS label_status,
            l.tracking_number,
            CASE WHEN a.state='purchased' AND l.void_status NOT IN
              ('voided','pending','uncertain') THEN l.id END AS label_id,
            p.provider_code
          FROM orders o
          LEFT JOIN label_attempts a ON a.id=(SELECT id FROM label_attempts
            WHERE order_id=o.id ORDER BY created_at DESC,id DESC LIMIT 1)
          LEFT JOIN labels l ON l.attempt_id=a.id
          LEFT JOIN provider_accounts p ON p.id=a.provider_account_id
        ) SELECT * FROM listed WHERE
          (:status='all' OR (:status='new' AND label_status IS NULL)
           OR label_status=:status OR (:status='attention' AND
             label_status IS NOT NULL AND label_status NOT IN ('purchased','removed')))
          AND (instr(lower(COALESCE(wms_order_no,'') || ' ' ||
            COALESCE(platform_reference,'') || ' ' || COALESCE(recipient_name,'') || ' ' ||
            COALESCE(tracking_number,'')), :search)>0)
        ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset
    """
    with request.app.state.engine.connect() as db:
        return [
            dict(row)
            for row in db.execute(
                text(query),
                {
                    "status": status,
                    "search": search.strip().lower(),
                    "offset": offset,
                    "limit": limit,
                },
            ).mappings()
        ]


@router.get("/api/orders/{order_id}")
def order_detail(order_id: str, request: Request):
    with request.app.state.engine.connect() as db:
        result = load_order(db, order_id)
        result["default_ship_date"] = default_ship_date()
        return result
