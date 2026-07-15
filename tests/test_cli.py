"""Test per la CLI Typer (payroll_ingest.cli) con typer.testing.CliRunner.

DATABASE_URL/PAYROLL_BASE_DIR non vengono passate per env: monkeypatchiamo
direttamente get_settings (per puntare a tmp_path, mai a input/processed/error
reali) e make_session_factory (per riusare la sessione/schema Postgres isolato
di test invece di aprire un nuovo engine sullo schema 'public' reale)."""

import uuid

from sqlalchemy import select
from typer.testing import CliRunner

import payroll_ingest.cli as cli_module
from payroll_ingest.config import Settings
from payroll_ingest.models import Anomaly, AuditEvent, Company, PayrollDocument, PayrollPeriod

runner = CliRunner()


def _patch_cli(monkeypatch, tmp_path, db_session_factory) -> Settings:
    settings = Settings(PAYROLL_BASE_DIR=tmp_path)
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "make_session_factory", lambda _settings: db_session_factory)
    return settings


def _sha() -> str:
    return uuid.uuid4().hex.ljust(64, "0")


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------


def test_process_command_no_files_exits_zero(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)

    result = runner.invoke(cli_module.app, ["process"])

    assert result.exit_code == 0
    assert "0 file" in result.output


def test_process_command_failure_exits_one(tmp_path, db_session_factory, monkeypatch):
    settings = _patch_cli(monkeypatch, tmp_path, db_session_factory)
    settings.ensure_folders()
    (settings.input_dir / "garbage.pdf").write_bytes(b"not a real pdf at all, just noise")

    result = runner.invoke(cli_module.app, ["process"])

    assert result.exit_code == 1
    assert "in errore" in result.output
    assert (settings.error_dir / "garbage.pdf").exists()


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_export_command_creates_bundle_with_data(tmp_path, db_session_factory, monkeypatch):
    settings = _patch_cli(monkeypatch, tmp_path, db_session_factory)
    settings.ensure_folders()
    unique_name = f"CLI EXPORT CO {uuid.uuid4().hex}"

    setup = db_session_factory()
    try:
        setup.add(Company(ragione_sociale=unique_name))
        setup.commit()
    finally:
        setup.close()

    result = runner.invoke(cli_module.app, ["export"])

    assert result.exit_code == 0
    assert "Export creato in" in result.output

    bundles = list(settings.export_dir.iterdir())
    assert len(bundles) == 1
    company_lines = (bundles[0] / "company.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(unique_name in line for line in company_lines)


# ---------------------------------------------------------------------------
# delete-document
# ---------------------------------------------------------------------------


def test_delete_document_requires_exactly_one_filter(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)

    result = runner.invoke(cli_module.app, ["delete-document"])

    assert result.exit_code == 1
    assert "Specifica esattamente uno" in result.output


def test_delete_document_both_filename_and_sha256_is_rejected(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)

    result = runner.invoke(cli_module.app, ["delete-document", "--filename", "x.pdf", "--sha256", "abc"])

    assert result.exit_code == 1
    assert "Specifica esattamente uno" in result.output


def test_delete_document_not_found(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)

    result = runner.invoke(cli_module.app, ["delete-document", "--sha256", _sha()])

    assert result.exit_code == 1
    assert "Nessun documento trovato" in result.output


def test_delete_document_invalid_uuid(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)

    result = runner.invoke(cli_module.app, ["delete-document", "--id", "not-a-uuid"])

    assert result.exit_code == 1
    assert "non e' un UUID valido" in result.output


def test_delete_document_multiple_matches_lists_them_and_exits_one(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)
    filename = f"ambiguo_{uuid.uuid4().hex}.pdf"

    setup = db_session_factory()
    try:
        setup.add_all(
            [
                PayrollDocument(
                    sha256=_sha(),
                    original_filename=filename,
                    status="NEEDS_REVIEW",
                    template_name="unknown",
                    parser_version="1.0.0",
                    source_used_ocr=False,
                ),
                PayrollDocument(
                    sha256=_sha(),
                    original_filename=filename,
                    status="NEEDS_REVIEW",
                    template_name="unknown",
                    parser_version="1.0.0",
                    source_used_ocr=False,
                ),
            ]
        )
        setup.commit()
    finally:
        setup.close()

    result = runner.invoke(cli_module.app, ["delete-document", "--filename", filename])

    assert result.exit_code == 1
    assert "documenti corrispondono" in result.output
    assert filename in result.output


def test_delete_document_confirmed_with_yes_flag_deletes_row_and_audit(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)
    sha = _sha()

    setup = db_session_factory()
    try:
        doc = PayrollDocument(
            sha256=sha,
            original_filename="todelete.pdf",
            status="NEEDS_REVIEW",
            template_name="unknown",
            parser_version="1.0.0",
            source_used_ocr=False,
        )
        setup.add(doc)
        setup.flush()
        setup.add(AuditEvent(document_id=doc.id, run_id="r1", event_type="document_processed", detail={}))
        setup.commit()
        doc_id = doc.id
    finally:
        setup.close()

    result = runner.invoke(cli_module.app, ["delete-document", "--sha256", sha, "--yes"])

    assert result.exit_code == 0
    assert "Documento cancellato" in result.output

    verify = db_session_factory()
    try:
        assert verify.scalar(select(PayrollDocument).where(PayrollDocument.sha256 == sha)) is None
        assert verify.scalar(select(AuditEvent).where(AuditEvent.document_id == doc_id)) is None
    finally:
        verify.rollback()
        verify.close()


def test_delete_document_declined_confirmation_keeps_row(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)
    sha = _sha()

    setup = db_session_factory()
    try:
        setup.add(
            PayrollDocument(
                sha256=sha,
                original_filename="keep.pdf",
                status="NEEDS_REVIEW",
                template_name="unknown",
                parser_version="1.0.0",
                source_used_ocr=False,
            )
        )
        setup.commit()
    finally:
        setup.close()

    result = runner.invoke(cli_module.app, ["delete-document", "--sha256", sha], input="n\n")

    assert result.exit_code == 0
    assert "Annullato" in result.output

    verify = db_session_factory()
    try:
        assert verify.scalar(select(PayrollDocument).where(PayrollDocument.sha256 == sha)) is not None
    finally:
        verify.rollback()
        verify.close()


def test_delete_document_by_id(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)

    setup = db_session_factory()
    try:
        doc = PayrollDocument(
            sha256=_sha(),
            original_filename="byid.pdf",
            status="NEEDS_REVIEW",
            template_name="unknown",
            parser_version="1.0.0",
            source_used_ocr=False,
        )
        setup.add(doc)
        setup.commit()
        doc_id = doc.id
    finally:
        setup.close()

    result = runner.invoke(cli_module.app, ["delete-document", "--id", str(doc_id), "--yes"])

    assert result.exit_code == 0
    verify = db_session_factory()
    try:
        assert verify.get(PayrollDocument, doc_id) is None
    finally:
        verify.rollback()
        verify.close()


# ---------------------------------------------------------------------------
# check-years
# ---------------------------------------------------------------------------


def test_check_years_command_reports_problems_and_exits_one(tmp_path, db_session_factory, monkeypatch):
    _patch_cli(monkeypatch, tmp_path, db_session_factory)
    anno = 94000 + (uuid.uuid4().int % 1000)

    setup = db_session_factory()
    try:
        period = PayrollPeriod(mese=1, anno=anno, tipo="ordinario", label_originale="test cli")
        setup.add(period)
        setup.flush()
        doc_ok = PayrollDocument(
            sha256=_sha(),
            original_filename="ok.pdf",
            status="PROCESSED",
            template_name="zucchetti_standard",
            parser_version="1.0.0",
            source_used_ocr=False,
            period_id=period.id,
        )
        doc_bad = PayrollDocument(
            sha256=_sha(),
            original_filename="bad.pdf",
            status="NEEDS_REVIEW",
            template_name="zucchetti_standard",
            parser_version="1.0.0",
            source_used_ocr=False,
            period_id=period.id,
        )
        setup.add_all([doc_ok, doc_bad])
        setup.flush()
        setup.add(Anomaly(document_id=doc_bad.id, tipo="test", severita="error", messaggio="motivo di test"))
        setup.commit()
    finally:
        setup.close()

    result = runner.invoke(cli_module.app, ["check-years"])

    assert result.exit_code == 1
    assert "bad.pdf" in result.output
    assert str(anno) in result.output
    assert "motivo di test" in result.output
