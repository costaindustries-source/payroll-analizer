import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from sqlalchemy import delete, select

from payroll_ingest.config import Settings
from payroll_ingest.db import session_scope
from payroll_ingest.dto import (
    AnomalyDTO,
    AnomalySeverity,
    CompanyDTO,
    DocumentStatus,
    EmployeeDTO,
    PayrollDocumentDTO,
    PeriodDTO,
    PeriodType,
)
from payroll_ingest.extraction import extract_document
from payroll_ingest.hashing import sha256_file
from payroll_ingest.models import AuditEvent, PayrollDocument
from payroll_ingest.ocr import run_ocr
from payroll_ingest.pdf_classify import PdfKind, classify_pdf
from payroll_ingest.repository import save_document
from payroll_ingest.templates.zucchetti import PARSER_VERSION, is_zucchetti_document, map_document
from payroll_ingest.validation import validate

logger = structlog.get_logger()


@dataclass
class RunSummary:
    run_id: str
    total: int = 0
    processed: int = 0
    processed_with_anomalies: int = 0
    needs_review: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "total": self.total,
            "processed": self.processed,
            "processed_with_anomalies": self.processed_with_anomalies,
            "needs_review": self.needs_review,
            "failed": self.failed,
            "skipped": self.skipped,
        }


def _unrecognized_dto(reason: str) -> PayrollDocumentDTO:
    dto = PayrollDocumentDTO(
        company=CompanyDTO(ragione_sociale=""),
        employee=EmployeeDTO(cognome_nome="", codice_fiscale=""),
        period=PeriodDTO(mese=0, anno=0, tipo=PeriodType.ORDINARIO, label_originale=""),
        template_name="unknown",
    )
    dto.anomalies.append(
        AnomalyDTO(
            tipo="template_non_riconosciuto",
            severita=AnomalySeverity.ERROR,
            messaggio=reason,
            campo=None,
        )
    )
    return dto


def _determine_status(dto: PayrollDocumentDTO) -> DocumentStatus:
    if any(a.severita == AnomalySeverity.ERROR for a in dto.anomalies):
        return DocumentStatus.NEEDS_REVIEW
    if dto.anomalies:
        return DocumentStatus.PROCESSED_WITH_ANOMALIES
    return DocumentStatus.PROCESSED


def _destination_path(
    settings: Settings, status: DocumentStatus, dto: PayrollDocumentDTO, filename: str, sha256: str
) -> Path:
    # Qualunque esito puo' ricevere due documenti distinti (sha256 diversi, es.
    # cedolini di persone/aziende diverse) con lo stesso original_filename nello
    # stesso path di destinazione (v. issue GH #2 e #19): il prefisso hash evita
    # che il secondo shutil.move sovrascriva silenziosamente il file del primo
    # documento gia' processato, anche quando il periodo e' stato riconosciuto.
    if status == DocumentStatus.FAILED:
        return settings.error_dir / f"{sha256[:8]}_{filename}"
    if dto.period.mese and dto.period.anno:
        return settings.processed_dir / str(dto.period.anno) / f"{dto.period.mese:02d}" / f"{sha256[:8]}_{filename}"
    return settings.processed_dir / "non_riconosciuti" / f"{sha256[:8]}_{filename}"


def process_document(settings: Settings, session_factory, run_id: str, pdf_path: Path) -> DocumentStatus | None:
    """Elabora un singolo documento in isolamento. Il chiamante (run_batch) si
    aspetta che qualsiasi eccezione qui dentro venga propagata e gestita a
    livello di singolo file, senza mai interrompere gli altri documenti del batch."""
    log = logger.bind(run_id=run_id, file=pdf_path.name)
    digest = sha256_file(pdf_path)
    log = log.bind(sha256=digest)

    with session_scope(session_factory) as session:
        existing = session.scalar(select(PayrollDocument).where(PayrollDocument.sha256 == digest))
        if existing is not None:
            if existing.status in (
                DocumentStatus.PROCESSED.value,
                DocumentStatus.PROCESSED_WITH_ANOMALIES.value,
            ):
                log.info("duplicate_skip", existing_status=existing.status, existing_document_id=str(existing.id))
                duplicate_dir = settings.processed_dir / "duplicati"
                duplicate_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(pdf_path), str(duplicate_dir / pdf_path.name))
                return None
            # NEEDS_REVIEW: il documento ha gia' una riga in DB (sha256 e' UNIQUE),
            # ma non e' un esito terminale positivo -> il reprocessing e' consentito
            # (§10 del piano) e richiede di rimuovere prima il record precedente
            # (audit_event non e' in cascade dalla FK, va cancellato a parte).
            log.info("reprocessing_previous_needs_review", existing_document_id=str(existing.id))
            session.execute(delete(AuditEvent).where(AuditEvent.document_id == existing.id))
            session.delete(existing)

    ocr_used = False
    work_path = pdf_path
    kind = classify_pdf(pdf_path, settings.text_layer_min_chars)
    if kind == PdfKind.SCANNED:
        ocr_path = settings.work_dir / f"{pdf_path.stem}.ocr.pdf"
        run_ocr(pdf_path, ocr_path, language=settings.ocr_language)
        work_path = ocr_path
        ocr_used = True

    try:
        raw = extract_document(work_path, ocr_used=ocr_used)

        if is_zucchetti_document(raw):
            dto = map_document(raw)
        else:
            dto = _unrecognized_dto("Layout non riconosciuto come cedolino Zucchetti")

        dto.anomalies.extend(validate(dto))
        status = _determine_status(dto)

        # Il file va spostato PRIMA di committare il record: se il move fallisce
        # (permessi, disco pieno, ...) l'eccezione risale a run_batch senza che
        # nessuna riga sia mai stata scritta, cosi' status=PROCESSED implica
        # sempre file presente su disco (v. issue GH #18 - in precedenza il
        # commit avveniva prima del move, lasciando il DB con status=PROCESSED
        # e processed_path=NULL se il move falliva, e bloccando il reprocessing
        # per via del vincolo UNIQUE su sha256).
        destination = _destination_path(settings, status, dto, pdf_path.name, digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pdf_path), str(destination))

        try:
            with session_scope(session_factory) as session:
                document = save_document(
                    session,
                    sha256=digest,
                    original_filename=pdf_path.name,
                    status=status.value,
                    template_name=dto.template_name,
                    parser_version=PARSER_VERSION,
                    source_used_ocr=ocr_used,
                    dto=dto,
                    raw=raw,
                )
                document.processed_path = str(destination)
                session.add(
                    AuditEvent(
                        document_id=document.id,
                        run_id=run_id,
                        event_type="document_processed",
                        detail={"status": status.value, "anomalies": len(dto.anomalies)},
                    )
                )
                document_uuid = document.id
        except Exception:
            # Il file e' gia' stato spostato ma la riga non e' stata scritta: lo
            # riportiamo al path originale cosi' che _write_error_sidecar (che
            # opera su pdf_path) trovi il file dove si aspetta di trovarlo,
            # invece di fallire a sua volta e interrompere l'intero batch.
            shutil.move(str(destination), str(pdf_path))
            raise

        log.info(
            "document_processed",
            status=status.value,
            document_id=str(document_uuid),
            anomalies=len(dto.anomalies),
            destination=str(destination),
        )
        return status
    finally:
        if ocr_used and work_path != pdf_path and work_path.exists():
            work_path.unlink()


def _write_error_sidecar(settings: Settings, pdf_path: Path, run_id: str, error: Exception) -> Path:
    destination = settings.error_dir / pdf_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf_path), str(destination))
    sidecar = destination.with_suffix(destination.suffix + ".error.json")
    sidecar.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "file": pdf_path.name,
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return destination


def run_batch(settings: Settings, session_factory, run_id: str) -> RunSummary:
    settings.ensure_folders()
    summary = RunSummary(run_id=run_id)
    log = logger.bind(run_id=run_id)

    pdf_files = sorted(settings.input_dir.glob("*.pdf"))
    summary.total = len(pdf_files)
    log.info("run_started", total_files=summary.total)

    for pdf_path in pdf_files:
        try:
            status = process_document(settings, session_factory, run_id, pdf_path)
        except Exception as exc:  # noqa: BLE001 - isolamento per documento, non deve fermare il batch
            log.error("document_failed", file=pdf_path.name, error=str(exc), exc_info=True)
            _write_error_sidecar(settings, pdf_path, run_id, exc)
            summary.failed += 1
            summary.errors.append(f"{pdf_path.name}: {exc}")
            continue

        if status is None:
            summary.skipped += 1
        elif status == DocumentStatus.PROCESSED:
            summary.processed += 1
        elif status == DocumentStatus.PROCESSED_WITH_ANOMALIES:
            summary.processed_with_anomalies += 1
        elif status == DocumentStatus.NEEDS_REVIEW:
            summary.needs_review += 1

    log.info("run_completed", **summary.as_dict())

    run_log_path = settings.logs_dir / f"run_{run_id}.json"
    run_log_path.write_text(json.dumps(summary.as_dict(), indent=2), encoding="utf-8")

    return summary
