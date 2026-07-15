import fitz

from payroll_ingest.pdf_classify import PdfKind, classify_pdf


def _make_pdf(path, texts):
    # crea un PDF sintetico con una pagina per ogni stringa in `texts`
    # (pagina senza testo se la stringa e' vuota, per simulare uno scan)
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_classify_pdf_textual_with_enough_chars(tmp_path):
    path = tmp_path / "textual.pdf"
    _make_pdf(path, ["Questo e' un cedolino con parecchio testo estraibile dalla pagina."])
    assert classify_pdf(path) == PdfKind.TEXTUAL


def test_classify_pdf_scanned_with_no_text(tmp_path):
    path = tmp_path / "scanned.pdf"
    _make_pdf(path, [""])
    assert classify_pdf(path) == PdfKind.SCANNED


def test_classify_pdf_scanned_below_threshold(tmp_path):
    path = tmp_path / "few_chars.pdf"
    _make_pdf(path, ["abc"])  # 3 caratteri < soglia di default 20
    assert classify_pdf(path) == PdfKind.SCANNED


def test_classify_pdf_averages_across_pages(tmp_path):
    # una pagina ricca di testo e una vuota: la media puo' restare sopra soglia
    path = tmp_path / "mixed.pdf"
    _make_pdf(path, ["testo" * 20, ""])
    assert classify_pdf(path) == PdfKind.TEXTUAL


def test_classify_pdf_custom_min_chars_per_page(tmp_path):
    path = tmp_path / "custom.pdf"
    _make_pdf(path, ["poco testo qui"])
    assert classify_pdf(path, min_chars_per_page=100) == PdfKind.SCANNED
    assert classify_pdf(path, min_chars_per_page=5) == PdfKind.TEXTUAL
