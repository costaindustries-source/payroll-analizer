import subprocess
import sys
from pathlib import Path

import ocrmypdf

import payroll_ingest.ocr as ocr_module

# ocrmypdf e' importato dentro run_ocr() (non a livello di modulo, v. ocr.py):
# il monkeypatch va sul modulo reale in sys.modules, che e' lo stesso oggetto
# che l'import differito recupera dalla cache di import di Python.


def test_ocrmypdf_is_not_imported_at_module_load():
    """Guardia contro la regressione GH #25: importare ocrmypdf (non chiamarlo,
    il solo import) corrompeva la decodifica CID/ToUnicode di pdfminer per
    alcuni font degeneri, facendo fallire il riconoscimento del template su
    12/57 cedolini reali in batch, nonostante l'estrazione isolata (senza
    ocrmypdf mai importato nel processo) funzionasse. Processo separato,
    perche' nel runner dei test ocrmypdf e' gia' stato importato (v. sopra) e
    la condizione non sarebbe piu' rilevabile."""
    script = "import sys; import payroll_ingest.ocr; print('ocrmypdf' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.stdout.strip() == "False", (
        "payroll_ingest.ocr importa ocrmypdf a livello di modulo: v. issue GH #25, "
        "va importato solo dentro run_ocr()"
    )


def test_run_ocr_creates_output_parent_dir(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ocrmypdf, "ocr", lambda *a, **kw: calls.append((a, kw)))

    source = tmp_path / "in.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    output = tmp_path / "sub" / "out.pdf"

    ocr_module.run_ocr(source, output)

    assert output.parent.is_dir()
    assert len(calls) == 1


def test_run_ocr_passes_expected_arguments(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ocrmypdf, "ocr", lambda *a, **kw: calls.append((a, kw)))

    source = tmp_path / "in.pdf"
    output = tmp_path / "out.pdf"

    ocr_module.run_ocr(source, output, language="eng")

    args, kwargs = calls[0]
    assert args == (source, output)
    assert kwargs["language"] == "eng"
    assert kwargs["skip_text"] is False
    assert kwargs["force_ocr"] is True
    assert kwargs["progress_bar"] is False


def test_run_ocr_default_language_is_italian(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ocrmypdf, "ocr", lambda *a, **kw: calls.append(kw))

    ocr_module.run_ocr(tmp_path / "in.pdf", tmp_path / "out.pdf")

    assert calls[0]["language"] == "ita"


def test_run_ocr_propagates_errors_from_ocrmypdf(tmp_path, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("ocr fallito")

    monkeypatch.setattr(ocrmypdf, "ocr", _boom)

    try:
        ocr_module.run_ocr(tmp_path / "in.pdf", tmp_path / "out.pdf")
        raised = False
    except RuntimeError:
        raised = True
    assert raised
