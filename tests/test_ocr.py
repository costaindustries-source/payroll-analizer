from pathlib import Path

import payroll_ingest.ocr as ocr_module


def test_run_ocr_creates_output_parent_dir(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ocr_module.ocrmypdf, "ocr", lambda *a, **kw: calls.append((a, kw)))

    source = tmp_path / "in.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    output = tmp_path / "sub" / "out.pdf"

    ocr_module.run_ocr(source, output)

    assert output.parent.is_dir()
    assert len(calls) == 1


def test_run_ocr_passes_expected_arguments(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ocr_module.ocrmypdf, "ocr", lambda *a, **kw: calls.append((a, kw)))

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
    monkeypatch.setattr(ocr_module.ocrmypdf, "ocr", lambda *a, **kw: calls.append(kw))

    ocr_module.run_ocr(tmp_path / "in.pdf", tmp_path / "out.pdf")

    assert calls[0]["language"] == "ita"


def test_run_ocr_propagates_errors_from_ocrmypdf(tmp_path, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("ocr fallito")

    monkeypatch.setattr(ocr_module.ocrmypdf, "ocr", _boom)

    try:
        ocr_module.run_ocr(tmp_path / "in.pdf", tmp_path / "out.pdf")
        raised = False
    except RuntimeError:
        raised = True
    assert raised
