"""Add the platform reference number without resizing or covering carrier artwork."""

import io
import math
import threading

import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

# PDFium is not thread safe, even across independent documents.
_render_lock = threading.Lock()


def reference_label_pdf(original: bytes, platform_reference: str | None) -> bytes:
    reference = (platform_reference or "").strip() or "N/A"
    text = f"Platform Reference Number: {reference}"
    if any(ord(c) < 32 or ord(c) > 126 for c in reference):
        raise ValueError("Platform reference must contain printable English letters/numbers.")
    reader = PdfReader(io.BytesIO(original), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
        raise ValueError("Use an unencrypted PDF with 1-20 pages.")
    writer = PdfWriter(clone_from=reader)
    for page in writer.pages:
        if float(page.get("/UserUnit", 1)) != 1:
            raise ValueError("Unsupported PDF unit scale.")
        page.transfer_rotation_to_content()

    # Render the displayed artwork solely to find blank space. The output keeps
    # the original vector/image streams; barcodes are neither rasterized nor scaled.
    normalized = io.BytesIO()
    writer.write(normalized)
    with _render_lock, pdfium.PdfDocument(normalized.getvalue()) as document:
        for index, page in enumerate(writer.pages):
            width, height = float(page.cropbox.width), float(page.cropbox.height)
            if width <= 0 or height <= 0:
                raise ValueError("Invalid page size.")
            font_size = min(10, (width - 64) / stringWidth(text, "Helvetica-Bold", 1))
            if font_size < 7:
                raise ValueError("Platform reference is too long to fit legibly on this label.")
            text_width = stringWidth(text, "Helvetica-Bold", font_size)
            pdf_page = document[index]
            bitmap = pdf_page.render(scale=3)
            try:
                image = bitmap.to_pil().convert("L")
                position = None
                # Keep an extra 5pt of white clearance around the entire line,
                # including barcode quiet zones. Only use the bottom 1 inch.
                for y in range(9, min(72, int(height - font_size - 5)), 2):
                    for x in (9, max(9, width - text_width - 9)):
                        box = (
                            math.floor((x - 5) * 3),
                            math.floor((height - y - font_size - 5) * 3),
                            math.ceil((x + text_width + 5) * 3),
                            math.ceil((height - y + 7) * 3),
                        )
                        if image.crop(box).getextrema()[0] >= 250:
                            position = (x, y)
                            break
                    if position:
                        break
                if position is None:
                    raise ValueError(
                        "No safe blank area for the platform reference. Use the original PDF."
                    )
            finally:
                bitmap.close()
                pdf_page.close()
            overlay = io.BytesIO()
            canvas = Canvas(overlay, pagesize=(width, height))
            canvas.setFont("Helvetica-Bold", font_size)
            canvas.drawString(*position, text)
            canvas.save()
            page.merge_translated_page(
                PdfReader(overlay).pages[0], float(page.cropbox.left), float(page.cropbox.bottom)
            )
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()
