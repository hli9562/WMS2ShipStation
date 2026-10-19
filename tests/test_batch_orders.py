import io

import pypdfium2 as pdfium
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import text

from tests.test_purchases import setup_order
from wms2ship.config import Settings
from wms2ship.main import create_app


def test_search_filter_batch_preserves_pages_and_rejects_removed(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        labels = []
        for i in range(2):
            order, headers, payload = setup_order(client, number=f"BATCH-{i}")
            with client.app.state.engine.begin() as db:
                db.execute(
                    text("UPDATE orders SET platform_reference=:ref WHERE id=:id"),
                    {"ref": f"PLATFORM-{i}", "id": order},
                )
            result = client.post(
                f"/api/orders/{order}/label-attempts", json=payload, headers=headers
            ).json()
            labels.append(result["labels"][0]["id"])
        setup_order(client, number="UNSHIPPED")
        assert len(client.get("/api/orders?status=new").json()) == 1
        rows = client.get("/api/orders?status=purchased").json()
        assert len(rows) == 2
        assert (
            len(client.get("/api/orders", params={"search": rows[0]["tracking_number"]}).json())
            == 1
        )
        assert client.get("/api/orders", params={"search": rows[0]["recipient_name"]}).json()
        assert len(client.get("/api/orders?search=platform-0").json()) == 1
        assert len(client.get("/api/orders?limit=1&offset=1").json()) == 1
        response = client.post(
            "/api/labels/batch-print", json={"label_ids": labels + labels}, headers=headers
        )
        assert response.status_code == 200
        reader = PdfReader(io.BytesIO(response.content))
        assert len(reader.pages) == 2
        combined = pdfium.PdfDocument(response.content)
        for i, label in enumerate(labels):
            assert tuple(reader.pages[i].mediabox) == (0, 0, 288, 432)
            assert f"Platform Reference Number: PLATFORM-{i}" in reader.pages[i].extract_text()
            single = pdfium.PdfDocument(client.get(f"/api/labels/{label}/pdf").content)
            assert (
                combined[i].render(scale=1).to_pil().tobytes()
                == single[0].render(scale=1).to_pil().tobytes()
            )
            single.close()
        combined.close()
        with client.app.state.engine.begin() as db:
            assert db.execute(text("SELECT count(*) FROM label_attempts")).scalar() == 2
            db.execute(
                text("UPDATE labels SET void_status='voided' WHERE id=:id"), {"id": labels[0]}
            )
        assert (
            client.post(
                "/api/labels/batch-print", json={"label_ids": labels}, headers=headers
            ).status_code
            == 409
        )
        assert len(client.get("/api/orders?status=removed").json()) == 1
        assert client.get("/api/orders?status=removed").json()[0]["label_id"] is None
        assert (
            client.post(
                "/api/labels/batch-print", json={"label_ids": []}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/labels/batch-print", json={"label_ids": ["missing"]}, headers=headers
            ).status_code
            == 404
        )
