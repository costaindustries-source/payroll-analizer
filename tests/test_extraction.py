"""Verifica extract_document/extract_page su un PDF sintetico generato con
pymupdf (nessun cedolino reale disponibile: i campioni sono gitignored).
Le coordinate usate qui sono state validate empiricamente con pdfplumber
prima di scrivere le asserzioni (font Helvetica 10pt di default di fitz)."""

import fitz

from payroll_ingest.extraction import (
    SIDEBAR_MAX_X1,
    _is_scrambled_page,
    _reconstruct_words,
    extract_document,
)


def _make_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # striscia sidebar: x1 < SIDEBAR_MAX_X1, deve essere esclusa
    page.insert_text((18, 100), "Z", fontsize=10)
    # riga dati 1: due parole con lo stesso top -> stessa riga
    page.insert_text((100, 100), "Nome", fontsize=10)
    page.insert_text((200, 100), "Cognome", fontsize=10)
    # riga dati 2: top ben distante -> riga separata
    page.insert_text((100, 150), "Totale", fontsize=10)
    doc.save(path)
    doc.close()


def test_extract_document_excludes_sidebar_words(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)

    document = extract_document(path)
    page = document.first_page

    all_text = " ".join(w.text for w in page.words)
    assert "Z" not in [w.text for w in page.words]
    assert all(w.x1 > SIDEBAR_MAX_X1 for w in page.words)
    assert "Nome" in all_text
    assert "Totale" in all_text


def test_extract_document_clusters_words_into_rows(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)

    document = extract_document(path)
    page = document.first_page

    assert len(page.rows) == 2
    row_texts = [row.text for row in page.rows]
    assert row_texts[0] == "Nome Cognome"
    assert row_texts[1] == "Totale"


def test_extract_document_row_words_ordered_by_x0(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)

    document = extract_document(path)
    first_row = document.first_page.rows[0]
    assert [w.text for w in first_row.words] == ["Nome", "Cognome"]


def test_extract_document_full_text_joins_rows(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)

    document = extract_document(path)
    assert document.first_page.full_text == "Nome Cognome\nTotale"


def test_extract_document_page_dimensions(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)

    document = extract_document(path)
    page = document.first_page
    assert page.width == 595
    assert page.height == 842


def test_extract_document_default_ocr_used_false(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)

    document = extract_document(path)
    assert document.ocr_used is False
    assert document.source_path == path
    assert document.unmapped_rows == []


def test_extract_document_ocr_used_flag_propagated(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)

    document = extract_document(path, ocr_used=True)
    assert document.ocr_used is True


def test_extract_document_empty_page_has_no_rows(tmp_path):
    path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()

    document = extract_document(path)
    page = document.first_page
    assert page.rows == []
    assert page.words == []
    assert page.full_text == ""


def test_extract_document_multiple_pages(tmp_path):
    path = tmp_path / "two_pages.pdf"
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((100, 100), "PaginaUno", fontsize=10)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((100, 100), "PaginaDue", fontsize=10)
    doc.save(path)
    doc.close()

    document = extract_document(path)
    assert len(document.pages) == 2
    assert document.pages[0].full_text == "PaginaUno"
    assert document.pages[1].full_text == "PaginaDue"
    assert document.first_page is document.pages[0]


# ---------------------------------------------------------------------------
# Recupero testo per font Win2PDF a avanzamento zero (v.
# docs/PIANO_TECNICO_NEW_TEMPLATES.md §3): un font del genere fa si' che tutti
# i frammenti di una parola condividano lo stesso x0. fitz/pymupdf usa sempre
# metriche di font corrette, quindi per riprodurre il sintomo (non la causa)
# inseriamo ogni singolo carattere allo STESSO punto di origine: pdfplumber
# osserva comunque x0 identico tra frammenti distinti nello stesso ordine di
# stream, verificato empiricamente essere indistinguibile - ai fini di
# _is_scrambled_page/_reconstruct_words - dal bug reale sui campioni Win2PDF.
# ---------------------------------------------------------------------------


def _make_scrambled_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((18, 100), "Z", fontsize=10)  # sidebar, deve restare esclusa
    for ch in "TOTALE":
        page.insert_text((100, 100), ch, fontsize=10)
    for ch in "NETTO":
        page.insert_text((300, 100), ch, fontsize=10)
    doc.save(path)
    doc.close()


def test_is_scrambled_page_true_for_repeated_x0():
    chars = [{"text": ch, "x0": 100.0, "x1": 105.0, "top": 50.0, "bottom": 60.0} for ch in "TOTALE"]
    assert _is_scrambled_page(chars) is True


def test_is_scrambled_page_false_for_increasing_x0():
    chars = [
        {"text": ch, "x0": 100.0 + i * 6.0, "x1": 100.0 + i * 6.0 + 5.0, "top": 50.0, "bottom": 60.0}
        for i, ch in enumerate("TOTALE")
    ]
    assert _is_scrambled_page(chars) is False


def test_is_scrambled_page_false_for_fewer_than_two_chars():
    assert _is_scrambled_page([]) is False
    assert _is_scrambled_page([{"text": "A", "x0": 1.0, "x1": 2.0, "top": 1.0, "bottom": 2.0}]) is False


def test_reconstruct_words_merges_same_x0_fragments_in_stream_order():
    chars = [{"text": ch, "x0": 100.0, "x1": 106.0, "top": 50.0, "bottom": 60.0} for ch in "TOTALE"]
    words = _reconstruct_words(chars)
    assert len(words) == 1
    assert words[0].text == "TOTALE"
    assert words[0].x0 == 100.0


def test_reconstruct_words_splits_on_x0_jump():
    chars = [
        {"text": "T", "x0": 100.0, "x1": 106.0, "top": 50.0, "bottom": 60.0},
        {"text": "O", "x0": 100.0, "x1": 106.0, "top": 50.0, "bottom": 60.0},
        {"text": "N", "x0": 300.0, "x1": 306.0, "top": 50.0, "bottom": 60.0},
        {"text": "E", "x0": 300.0, "x1": 306.0, "top": 50.0, "bottom": 60.0},
    ]
    words = _reconstruct_words(chars)
    assert [w.text for w in words] == ["TO", "NE"]


def test_reconstruct_words_splits_on_row_change():
    chars = [
        {"text": "A", "x0": 100.0, "x1": 106.0, "top": 50.0, "bottom": 60.0},
        {"text": "B", "x0": 100.0, "x1": 106.0, "top": 200.0, "bottom": 210.0},
    ]
    words = _reconstruct_words(chars)
    assert [w.text for w in words] == ["A", "B"]


def test_extract_document_recovers_scrambled_text(tmp_path):
    path = tmp_path / "scrambled.pdf"
    _make_scrambled_pdf(path)

    document = extract_document(path)
    page = document.first_page

    assert page.recovered_from_scramble is True
    assert "Z" not in [w.text for w in page.words]
    assert page.full_text == "TOTALE NETTO"


def test_extract_document_normal_text_not_marked_recovered(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)

    document = extract_document(path)
    assert document.first_page.recovered_from_scramble is False
