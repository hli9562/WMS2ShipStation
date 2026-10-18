import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from sqlalchemy import text

from tests.test_purchases import setup_order
from wms2ship.config import Settings
from wms2ship.labels import letter_pdf
from wms2ship.main import create_app
from wms2ship.providers import demo_pdf


def test_letter_preserves_size_rotation_and_content():
    # Turn the demo into a compact label without changing its content stream.
    reader = PdfReader(io.BytesIO(demo_pdf()))
    page = reader.pages[0]
    page.mediabox.upper_right = (288, 432)
    page.cropbox.upper_right = (288, 432)
    writer = PdfWriter()
    writer.add_page(page)
    stream = io.BytesIO()
    writer.write(stream)
    compact = stream.getvalue()
    result = PdfReader(io.BytesIO(letter_pdf(compact)))
    assert tuple(result.pages[0].mediabox) == (0, 0, 612, 792)
    # Translation only: never magnify the original label/barcode.
    assert (
        b"1 0.0 0.0 1" in result.pages[0].get_contents().get_data()
        or b"1 0 0 1" in result.pages[0].get_contents().get_data()
    )
    assert "SIMULATION" in result.pages[0].extract_text()
    wide = PdfWriter()
    wide.add_blank_page(width=900, height=1000)
    oversized = io.BytesIO()
    wide.write(oversized)
    with pytest.raises(ValueError, match="without scaling"):
        letter_pdf(oversized.getvalue())


def test_reprint_history_and_missing_artifact_do_not_repurchase(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        order_id, headers, payload = setup_order(client)
        attempt = client.post(
            f"/api/orders/{order_id}/label-attempts", json=payload, headers=headers
        ).json()
        label_id = attempt["labels"][0]["id"]
        for _ in range(2):
            response = client.get(f"/api/labels/{label_id}/pdf")
            assert response.status_code == 200
            assert response.content == demo_pdf()
            assert tuple(PdfReader(io.BytesIO(response.content)).pages[0].mediabox) == (
                0,
                0,
                288,
                432,
            )
        letter = client.get(f"/api/labels/{label_id}/pdf?kind=letter")
        assert letter.status_code == 200
        assert tuple(PdfReader(io.BytesIO(letter.content)).pages[0].mediabox) == (0, 0, 612, 792)
        assert client.get(f"/api/labels/{label_id}/pdf?kind=original").content == demo_pdf()
        history = client.get("/api/history").json()
        assert history[0]["tracking_number"].startswith("SIMULATED-")
        assert history[0]["mode"] == "simulation"
        with client.app.state.engine.connect() as db:
            assert db.execute(text("SELECT count(*) FROM label_attempts")).scalar() == 1
            key = db.execute(
                text(
                    "SELECT storage_key FROM label_artifacts WHERE label_id=:id AND kind='original'"
                ),
                {"id": label_id},
            ).scalar()
        (settings.labels_dir / key).unlink()
        assert client.get(f"/api/labels/{label_id}/pdf?kind=original").status_code == 409
        recovered = client.post(
            f"/api/labels/{label_id}/recover",
            content=demo_pdf(),
            headers={
                **headers,
                "x-recovery-evidence": "Recovered the same original from the verified backup.",
            },
        )
        assert recovered.status_code == 200
        assert client.get(f"/api/labels/{label_id}/pdf?kind=original").content == demo_pdf()
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/api/history").json()) == 1
        assert client.get(f"/api/labels/{label_id}/pdf").status_code == 200
