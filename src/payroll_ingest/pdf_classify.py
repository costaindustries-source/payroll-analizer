from enum import Enum
from pathlib import Path

import fitz  # PyMuPDF


class PdfKind(str, Enum):
    TEXTUAL = "textual"
    SCANNED = "scanned"


def classify_pdf(path: Path, min_chars_per_page: int = 20) -> PdfKind:
    """Rileva se il PDF ha un layer testo utilizzabile (testuale/PDF-A) oppure e'
    scansionato (immagine senza testo estraibile, serve OCR)."""
    doc = fitz.open(path)
    try:
        total_chars = sum(len(page.get_text("text")) for page in doc)
        avg_chars = total_chars / max(doc.page_count, 1)
    finally:
        doc.close()
    return PdfKind.TEXTUAL if avg_chars >= min_chars_per_page else PdfKind.SCANNED
