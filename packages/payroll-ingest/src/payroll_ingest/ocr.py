import logging
from pathlib import Path

import ocrmypdf

logger = logging.getLogger(__name__)


def run_ocr(source_path: Path, output_path: Path, language: str = "ita") -> None:
    """Genera una copia del PDF con layer testo tramite OCR (Tesseract).
    Il file risultante puo' rientrare nel percorso di estrazione posizionale standard."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ocrmypdf.ocr(
        source_path,
        output_path,
        language=language,
        skip_text=False,
        force_ocr=True,
        progress_bar=False,
    )
