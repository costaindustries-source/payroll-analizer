import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run_ocr(source_path: Path, output_path: Path, language: str = "ita") -> None:
    """Genera una copia del PDF con layer testo tramite OCR (Tesseract).
    Il file risultante puo' rientrare nel percorso di estrazione posizionale standard.

    Import di ocrmypdf differito qui dentro (non a livello di modulo): importarlo
    e' di per se' sufficiente a corrompere la decodifica CID/ToUnicode di pdfminer
    (usato da pdfplumber) per alcuni font degeneri (v. issue GH #25 - i 12 file
    Win2PDF a font scramblato risultavano "template non riconosciuto" in batch
    reale nonostante extract_document+find_template li riconoscessero
    correttamente in isolamento, e il solo `import ocrmypdf` bastava a
    riprodurre il fallimento senza mai chiamare run_ocr). Il modulo va quindi
    caricato solo quando l'OCR e' davvero necessario (documenti scansionati),
    cosi' un batch di soli PDF testuali - il caso comune - non lo importa mai."""
    import ocrmypdf

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ocrmypdf.ocr(
        source_path,
        output_path,
        language=language,
        skip_text=False,
        force_ocr=True,
        progress_bar=False,
    )
