"""Test per payroll_ingest.orchestrator: process_document/run_batch.

Non esistono PDF reali di cedolini nel repo (dati personali, gitignored):
mockiamo le funzioni di estrazione/classificazione/mappatura importate da
orchestrator (classify_pdf, extract_document, find_template - v.
_mock_zucchetti_dispatch) e usiamo file con bytes qualunque solo per
sha256_file. Ogni
test usa `Settings(PAYROLL_BASE_DIR=tmp_path)`, mai le cartelle reali del repo.
NOTA: il campo si chiama `base_dir` ma ha alias Pydantic "PAYROLL_BASE_DIR" e
populate_by_name non e' abilitato in config.py: passare `base_dir=` al
costruttore viene silenziosamente ignorato e Settings ricade sul default
"." (repo reale!). Va sempre usato l'alias per costruire Settings con un
base_dir custom."""

import json
import random
import string
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

import payroll_ingest.orchestrator as orchestrator
from payroll_ingest.config import Settings
from payroll_ingest.dto import (
    AnomalyDTO,
    AnomalySeverity,
    CompanyDTO,
    DocumentStatus,
    EmployeeDTO,
    PayLineCategory,
    PayLineDTO,
    PayrollDocumentDTO,
    PeriodDTO,
    PeriodType,
)
from payroll_ingest.extraction import RawExtractedDocument, RawPage
from payroll_ingest.hashing import sha256_file
from payroll_ingest.models import AuditEvent, PayrollDocument
from payroll_ingest.pdf_classify import PdfKind
from payroll_ingest.templates._spec import TemplateSpec


def _fake_raw(path, rows=None) -> RawExtractedDocument:
    page = RawPage(words=[], rows=rows or [], full_text="", width=595.0, height=842.0)
    return RawExtractedDocument(source_path=path, pages=[page], ocr_used=False)


def _mock_zucchetti_dispatch(monkeypatch, map_fn, parser_version="1.0.0") -> None:
    """Sostituisce orchestrator.find_template con uno stub che finge un match
    Zucchetti e delega il mapping a map_fn, cosi' i test non dipendono
    dall'implementazione reale di is_zucchetti_document/map_document."""
    spec = TemplateSpec(name="zucchetti_standard", parser_version=parser_version, detect=lambda raw: True, map=map_fn)
    monkeypatch.setattr(orchestrator, "find_template", lambda raw: spec)


def _unique_bytes(tag: str) -> bytes:
    # process_document COMMITTA per davvero (session_scope) nello schema di test
    # condiviso per l'intera sessione pytest: contenuto fisso riprodurrebbe lo
    # stesso sha256 ad ogni riesecuzione della suite, facendo scattare la
    # rilevazione duplicati invece del path atteso dal test. Bytes randomici a
    # ogni chiamata evitano la collisione.
    return f"{tag}-{uuid.uuid4().hex}".encode()


def _valid_cf() -> str:
    """Codice fiscale di formato valido per _CF_RE (validation.py controlla solo
    il formato, non il checksum), randomizzato per non collidere con l'identita'
    employee/company/periodo (UNIQUE su employee_id+company_id+period_id) creata
    da un'esecuzione precedente della stessa suite nello stesso schema."""
    letters6 = "".join(random.choices(string.ascii_uppercase, k=6))
    l1, l2, l3 = random.choices(string.ascii_uppercase, k=3)
    d2a, d2b = random.randint(0, 99), random.randint(0, 99)
    d3 = random.randint(0, 999)
    return f"{letters6}{d2a:02d}{l1}{d2b:02d}{l2}{d3:03d}{l3}"


def _clean_dto() -> PayrollDocumentDTO:
    """DTO che produce zero anomalie da validate() (CF di formato valido,
    almeno una pay_line, totals assente cosi' da non innescare i controlli di
    quadratura/IBAN) -> status PROCESSED. Azienda/dipendente/periodo random per
    non collidere con documenti gia' committati da esecuzioni precedenti."""
    anno = 90000 + random.randint(0, 9_999_999)
    mese = random.randint(1, 12)
    return PayrollDocumentDTO(
        company=CompanyDTO(ragione_sociale=f"ACME ORCHESTRATOR TEST SRL {uuid.uuid4().hex}"),
        employee=EmployeeDTO(cognome_nome="Mario Rossi", codice_fiscale=_valid_cf()),
        period=PeriodDTO(mese=mese, anno=anno, tipo=PeriodType.ORDINARIO, label_originale="periodo test"),
        pay_lines=[
            PayLineDTO(
                codice="F00100",
                descrizione="Retribuzione ordinaria",
                categoria=PayLineCategory.RETRIBUZIONE,
                is_recognized=True,
                competenza=Decimal("1000.00"),
                raw_text="riga di test",
            )
        ],
        template_name="zucchetti_standard",
    )


def _settings(tmp_path) -> Settings:
    settings = Settings(PAYROLL_BASE_DIR=tmp_path)
    settings.ensure_folders()
    return settings


# ---------------------------------------------------------------------------
# process_document - happy path
# ---------------------------------------------------------------------------


def test_process_document_happy_path_processed(tmp_path, db_session_factory, monkeypatch):
    settings = _settings(tmp_path)
    pdf_path = settings.input_dir / "cedolino.pdf"
    pdf_path.write_bytes(_unique_bytes("happy-path"))
    digest = sha256_file(pdf_path)
    dto = _clean_dto()

    monkeypatch.setattr(orchestrator, "classify_pdf", lambda path, min_chars: PdfKind.TEXTUAL)
    monkeypatch.setattr(orchestrator, "extract_document", lambda path, ocr_used=False: _fake_raw(path))
    _mock_zucchetti_dispatch(monkeypatch, lambda raw: dto)

    run_id = str(uuid.uuid4())
    status = orchestrator.process_document(settings, db_session_factory, run_id, pdf_path)

    assert status == DocumentStatus.PROCESSED
    expected_dest = (
        settings.processed_dir / str(dto.period.anno) / f"{dto.period.mese:02d}" / f"{digest[:8]}_cedolino.pdf"
    )
    assert expected_dest.exists()
    assert not pdf_path.exists()

    verify = db_session_factory()
    try:
        doc = verify.scalar(select(PayrollDocument).where(PayrollDocument.sha256 == digest))
        assert doc is not None
        assert doc.status == DocumentStatus.PROCESSED.value
        assert doc.processed_path == str(expected_dest)
    finally:
        verify.rollback()
        verify.close()


# ---------------------------------------------------------------------------
# (b) il move del file fallisce -> nessuna riga scritta in DB
# ---------------------------------------------------------------------------


def test_process_document_move_failure_writes_no_db_row(tmp_path, db_session_factory, monkeypatch):
    settings = _settings(tmp_path)
    pdf_path = settings.input_dir / "movefail.pdf"
    pdf_path.write_bytes(_unique_bytes("move-failure"))
    digest = sha256_file(pdf_path)

    monkeypatch.setattr(orchestrator, "classify_pdf", lambda path, min_chars: PdfKind.TEXTUAL)
    monkeypatch.setattr(orchestrator, "extract_document", lambda path, ocr_used=False: _fake_raw(path))
    _mock_zucchetti_dispatch(monkeypatch, lambda raw: _clean_dto())

    def failing_move(_src, _dst):
        raise OSError("simulated move failure")

    monkeypatch.setattr(orchestrator.shutil, "move", failing_move)

    run_id = str(uuid.uuid4())
    with pytest.raises(OSError):
        orchestrator.process_document(settings, db_session_factory, run_id, pdf_path)

    verify = db_session_factory()
    try:
        doc = verify.scalar(select(PayrollDocument).where(PayrollDocument.sha256 == digest))
        assert doc is None
    finally:
        verify.rollback()
        verify.close()

    assert pdf_path.exists()


# ---------------------------------------------------------------------------
# (c) il commit DB fallisce DOPO un move riuscito -> il file torna al path originale
# ---------------------------------------------------------------------------


def test_process_document_commit_failure_after_move_restores_original_file(tmp_path, db_session_factory, monkeypatch):
    settings = _settings(tmp_path)
    pdf_path = settings.input_dir / "commitfail.pdf"
    pdf_path.write_bytes(_unique_bytes("commit-failure"))
    digest = sha256_file(pdf_path)
    dto = _clean_dto()

    monkeypatch.setattr(orchestrator, "classify_pdf", lambda path, min_chars: PdfKind.TEXTUAL)
    monkeypatch.setattr(orchestrator, "extract_document", lambda path, ocr_used=False: _fake_raw(path))
    _mock_zucchetti_dispatch(monkeypatch, lambda raw: dto)

    call_count = {"n": 0}

    def factory_with_failing_second_commit():
        call_count["n"] += 1
        session = db_session_factory()
        if call_count["n"] >= 2:
            # La prima session_scope (controllo duplicati in testa a
            # process_document) deve commitare normalmente: solo la seconda
            # (quella di save_document) deve fallire, per simulare un errore
            # DOPO che il file e' gia' stato spostato con successo.
            def bad_commit():
                raise RuntimeError("simulated commit failure")

            session.commit = bad_commit
        return session

    run_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        orchestrator.process_document(settings, factory_with_failing_second_commit, run_id, pdf_path)

    assert call_count["n"] >= 2
    assert pdf_path.exists()
    expected_dest = (
        settings.processed_dir / str(dto.period.anno) / f"{dto.period.mese:02d}" / f"{digest[:8]}_commitfail.pdf"
    )
    assert not expected_dest.exists()

    verify = db_session_factory()
    try:
        doc = verify.scalar(select(PayrollDocument).where(PayrollDocument.sha256 == digest))
        assert doc is None
    finally:
        verify.rollback()
        verify.close()


# ---------------------------------------------------------------------------
# (d) stesso filename, sha256 diversi -> nessuna sovrascrittura
# ---------------------------------------------------------------------------


def test_process_document_same_filename_different_hash_no_overwrite(tmp_path, db_session_factory, monkeypatch):
    settings = _settings(tmp_path)

    monkeypatch.setattr(orchestrator, "classify_pdf", lambda path, min_chars: PdfKind.TEXTUAL)
    monkeypatch.setattr(orchestrator, "extract_document", lambda path, ocr_used=False: _fake_raw(path))
    # find_template NON mockato: un raw senza righe non matcha alcun template
    # registrato e produce sempre l'esito "non riconosciuto" reale (_unrecognized_dto).

    src_a = tmp_path / "srcA"
    src_b = tmp_path / "srcB"
    src_a.mkdir()
    src_b.mkdir()
    pdf_a = src_a / "cedolino.pdf"
    pdf_b = src_b / "cedolino.pdf"
    content_a = _unique_bytes("AAAA")
    content_b = _unique_bytes("BBBB")
    pdf_a.write_bytes(content_a)
    pdf_b.write_bytes(content_b)
    digest_a = sha256_file(pdf_a)
    digest_b = sha256_file(pdf_b)
    assert digest_a != digest_b

    run_id = str(uuid.uuid4())
    status_a = orchestrator.process_document(settings, db_session_factory, run_id, pdf_a)
    status_b = orchestrator.process_document(settings, db_session_factory, run_id, pdf_b)

    assert status_a == DocumentStatus.NEEDS_REVIEW
    assert status_b == DocumentStatus.NEEDS_REVIEW

    dest_a = settings.processed_dir / "non_riconosciuti" / f"{digest_a[:8]}_cedolino.pdf"
    dest_b = settings.processed_dir / "non_riconosciuti" / f"{digest_b[:8]}_cedolino.pdf"
    assert dest_a.exists()
    assert dest_b.exists()
    assert dest_a != dest_b
    assert dest_a.read_bytes() == content_a
    assert dest_b.read_bytes() == content_b


# ---------------------------------------------------------------------------
# Duplicati / reprocessing
# ---------------------------------------------------------------------------


def test_process_document_duplicate_processed_is_skipped(tmp_path, db_session_factory):
    settings = _settings(tmp_path)
    pdf_path = settings.input_dir / "dup.pdf"
    pdf_path.write_bytes(_unique_bytes("dup-processed"))
    digest = sha256_file(pdf_path)

    setup = db_session_factory()
    try:
        setup.add(
            PayrollDocument(
                sha256=digest,
                original_filename="dup.pdf",
                status=DocumentStatus.PROCESSED.value,
                template_name="zucchetti_standard",
                parser_version="1.0.0",
                source_used_ocr=False,
            )
        )
        setup.commit()
    finally:
        setup.close()

    run_id = str(uuid.uuid4())
    status = orchestrator.process_document(settings, db_session_factory, run_id, pdf_path)

    assert status is None
    dup_dest = settings.processed_dir / "duplicati" / "dup.pdf"
    assert dup_dest.exists()
    assert not pdf_path.exists()

    verify = db_session_factory()
    try:
        rows = verify.scalars(select(PayrollDocument).where(PayrollDocument.sha256 == digest)).all()
        assert len(rows) == 1
        assert rows[0].status == DocumentStatus.PROCESSED.value
    finally:
        verify.rollback()
        verify.close()


def test_process_document_reprocesses_previous_needs_review(tmp_path, db_session_factory, monkeypatch):
    settings = _settings(tmp_path)
    pdf_path = settings.input_dir / "retry.pdf"
    pdf_path.write_bytes(_unique_bytes("retry"))
    digest = sha256_file(pdf_path)

    setup = db_session_factory()
    try:
        old_doc = PayrollDocument(
            sha256=digest,
            original_filename="retry.pdf",
            status=DocumentStatus.NEEDS_REVIEW.value,
            template_name="unknown",
            parser_version="0.9.0",
            source_used_ocr=False,
        )
        setup.add(old_doc)
        setup.flush()
        setup.add(AuditEvent(document_id=old_doc.id, run_id="run-precedente", event_type="document_processed", detail={}))
        setup.commit()
        old_id = old_doc.id
    finally:
        setup.close()

    monkeypatch.setattr(orchestrator, "classify_pdf", lambda path, min_chars: PdfKind.TEXTUAL)
    monkeypatch.setattr(orchestrator, "extract_document", lambda path, ocr_used=False: _fake_raw(path))
    _mock_zucchetti_dispatch(monkeypatch, lambda raw: _clean_dto())

    run_id = str(uuid.uuid4())
    status = orchestrator.process_document(settings, db_session_factory, run_id, pdf_path)

    assert status == DocumentStatus.PROCESSED

    verify = db_session_factory()
    try:
        rows = verify.scalars(select(PayrollDocument).where(PayrollDocument.sha256 == digest)).all()
        assert len(rows) == 1
        assert rows[0].id != old_id
        assert rows[0].status == DocumentStatus.PROCESSED.value

        old_audit = verify.scalar(select(AuditEvent).where(AuditEvent.document_id == old_id))
        assert old_audit is None
    finally:
        verify.rollback()
        verify.close()


# ---------------------------------------------------------------------------
# Funzioni pure ausiliarie
# ---------------------------------------------------------------------------


def test_determine_status_no_anomalies_is_processed():
    dto = _clean_dto()
    assert orchestrator._determine_status(dto) == DocumentStatus.PROCESSED


def test_determine_status_only_warning_is_processed_with_anomalies():
    dto = _clean_dto()
    dto.anomalies.append(AnomalyDTO(tipo="x", severita=AnomalySeverity.WARNING, messaggio="m"))
    assert orchestrator._determine_status(dto) == DocumentStatus.PROCESSED_WITH_ANOMALIES


def test_determine_status_error_is_needs_review():
    dto = _clean_dto()
    dto.anomalies.append(AnomalyDTO(tipo="x", severita=AnomalySeverity.ERROR, messaggio="m"))
    assert orchestrator._determine_status(dto) == DocumentStatus.NEEDS_REVIEW


def test_unrecognized_dto_has_single_error_anomaly():
    dto = orchestrator._unrecognized_dto("motivo di test")
    assert dto.template_name == "unknown"
    assert len(dto.anomalies) == 1
    assert dto.anomalies[0].severita == AnomalySeverity.ERROR
    assert dto.anomalies[0].messaggio == "motivo di test"


def test_write_error_sidecar_moves_file_and_writes_json(tmp_path):
    settings = _settings(tmp_path)
    pdf_path = settings.input_dir / "err.pdf"
    pdf_path.write_bytes(b"broken")

    dest = orchestrator._write_error_sidecar(settings, pdf_path, "run123", ValueError("boom"))

    assert dest == settings.error_dir / "err.pdf"
    assert dest.exists()
    assert not pdf_path.exists()

    sidecar = dest.with_suffix(dest.suffix + ".error.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run123"
    assert payload["file"] == "err.pdf"
    assert payload["error_type"] == "ValueError"
    assert payload["error_message"] == "boom"


# ---------------------------------------------------------------------------
# run_batch
# ---------------------------------------------------------------------------


def test_run_batch_processes_all_files_and_isolates_failures(tmp_path, db_session_factory, monkeypatch):
    settings = Settings(PAYROLL_BASE_DIR=tmp_path)  # non chiamiamo ensure_folders: lo fa run_batch stesso
    settings.input_dir.mkdir(parents=True, exist_ok=True)
    good_pdf = settings.input_dir / "good.pdf"
    bad_pdf = settings.input_dir / "bad.pdf"
    good_pdf.write_bytes(_unique_bytes("run-batch-good"))
    bad_pdf.write_bytes(_unique_bytes("run-batch-bad"))

    def fake_extract(path, ocr_used=False):
        if path.name == "bad.pdf":
            raise ValueError("estrazione fallita simulata")
        return _fake_raw(path)

    monkeypatch.setattr(orchestrator, "classify_pdf", lambda path, min_chars: PdfKind.TEXTUAL)
    monkeypatch.setattr(orchestrator, "extract_document", fake_extract)
    _mock_zucchetti_dispatch(monkeypatch, lambda raw: _clean_dto())

    run_id = str(uuid.uuid4())
    summary = orchestrator.run_batch(settings, db_session_factory, run_id)

    assert summary.total == 2
    assert summary.processed == 1
    assert summary.failed == 1
    assert summary.skipped == 0
    assert len(summary.errors) == 1
    assert "bad.pdf" in summary.errors[0]

    error_pdf = settings.error_dir / "bad.pdf"
    assert error_pdf.exists()
    sidecar = error_pdf.with_suffix(error_pdf.suffix + ".error.json")
    assert sidecar.exists()

    run_log = settings.logs_dir / f"run_{run_id}.json"
    assert run_log.exists()
    payload = json.loads(run_log.read_text(encoding="utf-8"))
    assert payload["total"] == 2
    assert payload["processed"] == 1
    assert payload["failed"] == 1
    assert payload["run_id"] == run_id


def test_run_batch_counts_every_status_kind(tmp_path, db_session_factory, monkeypatch):
    """Copre gli ultimi rami non esercitati di run_batch: skipped (duplicato
    gia' processato), processed_with_anomalies e needs_review, oltre a
    processed gia' testato altrove."""
    settings = Settings(PAYROLL_BASE_DIR=tmp_path)
    settings.ensure_folders()

    processed_pdf = settings.input_dir / "processed.pdf"
    anomalie_pdf = settings.input_dir / "anomalie.pdf"
    review_pdf = settings.input_dir / "review.pdf"
    skipped_pdf = settings.input_dir / "skipped.pdf"
    processed_pdf.write_bytes(_unique_bytes("rb-processed"))
    anomalie_pdf.write_bytes(_unique_bytes("rb-anomalie"))
    review_pdf.write_bytes(_unique_bytes("rb-review"))
    skipped_pdf.write_bytes(_unique_bytes("rb-skipped"))

    skipped_digest = sha256_file(skipped_pdf)
    setup = db_session_factory()
    try:
        setup.add(
            PayrollDocument(
                sha256=skipped_digest,
                original_filename="skipped.pdf",
                status=DocumentStatus.PROCESSED.value,
                template_name="zucchetti_standard",
                parser_version="1.0.0",
                source_used_ocr=False,
            )
        )
        setup.commit()
    finally:
        setup.close()

    dto_processed = _clean_dto()
    dto_anomalie = _clean_dto()
    dto_anomalie.anomalies.append(AnomalyDTO(tipo="x", severita=AnomalySeverity.WARNING, messaggio="attenzione"))
    dto_review = _clean_dto()
    dto_review.anomalies.append(AnomalyDTO(tipo="x", severita=AnomalySeverity.ERROR, messaggio="grave"))

    dto_by_name = {
        "processed.pdf": dto_processed,
        "anomalie.pdf": dto_anomalie,
        "review.pdf": dto_review,
    }

    monkeypatch.setattr(orchestrator, "classify_pdf", lambda path, min_chars: PdfKind.TEXTUAL)
    monkeypatch.setattr(orchestrator, "extract_document", lambda path, ocr_used=False: _fake_raw(path))
    _mock_zucchetti_dispatch(monkeypatch, lambda raw: dto_by_name.get(raw.source_path.name))

    run_id = str(uuid.uuid4())
    summary = orchestrator.run_batch(settings, db_session_factory, run_id)

    assert summary.total == 4
    assert summary.processed == 1
    assert summary.processed_with_anomalies == 1
    assert summary.needs_review == 1
    assert summary.skipped == 1
    assert summary.failed == 0


def test_run_batch_with_no_pdf_files_is_a_noop(tmp_path, db_session_factory):
    settings = Settings(PAYROLL_BASE_DIR=tmp_path)
    run_id = str(uuid.uuid4())

    summary = orchestrator.run_batch(settings, db_session_factory, run_id)

    assert summary.total == 0
    assert summary.processed == 0
    assert summary.failed == 0
    assert summary.errors == []
