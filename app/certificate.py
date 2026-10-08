"""Certificate generation: one fixed template, drawn as a PDF with reportlab."""
import os
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


def generate_pdf(name: str, event_name: str, issued_on: str, path: str) -> None:
    """Draw one certificate (the fixed template) with the given name, event and date, and save it as a PDF at `path`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    w, h = landscape(A4)
    c = canvas.Canvas(path, pagesize=(w, h))
    c.setLineWidth(4)
    c.rect(30, 30, w - 60, h - 60)                       # border
    c.setFont("Helvetica-Bold", 38)
    c.drawCentredString(w / 2, h - 130, "Certificate of Completion")
    c.setFont("Helvetica", 16)
    c.drawCentredString(w / 2, h - 190, "This is to certify that")
    c.setFont("Helvetica-Bold", 32)
    c.drawCentredString(w / 2, h - 250, name)            # recipient-specific
    c.setFont("Helvetica", 16)
    c.drawCentredString(w / 2, h - 300, "has successfully completed")
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(w / 2, h - 345, event_name)      # recipient-specific
    c.setFont("Helvetica", 14)
    c.drawCentredString(w / 2, 80, f"Issued on {issued_on}")
    c.save()
