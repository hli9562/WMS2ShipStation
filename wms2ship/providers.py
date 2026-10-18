"""Provider-neutral purchase contract. No provider secrets in application records."""

from dataclasses import dataclass
from uuid import uuid4

from wms2ship.configuration import FAKE_CHOICES


class PurchaseRejected(Exception):
    """Provider conclusively rejected the request without purchasing postage."""


class PurchaseUncertain(Exception):
    """Provider may have purchased postage. Retain the package guard."""


@dataclass
class PurchaseResult:
    shipment_id: str | None
    label_id: str | None
    tracking: str | None
    pdf: bytes | None
    charge_minor: int | None = None
    currency: str | None = None


def demo_pdf():
    # A minimal valid Letter PDF with an unmistakable simulation watermark.
    stream = b"BT /F1 22 Tf 40 700 Td (SIMULATION - NOT VALID POSTAGE) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(pdf)
    pdf += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode()
    return pdf


class FakeProvider:
    code = "fake"
    mode = "simulation"

    def catalog(self):
        return FAKE_CHOICES

    def create_label(self, snapshot, attempt_id):
        return PurchaseResult(attempt_id, attempt_id, f"SIMULATED-{uuid4()}", demo_pdf(), 0, "USD")


def provider_mode(code):
    return {"fake": "simulation", "shipstation_test": "test"}.get(code, "live")
