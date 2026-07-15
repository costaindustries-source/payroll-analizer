"""Regressione per issue GH #2 (reprocessing con hash diverso sovrascriveva
silenziosamente il file precedente) e GH #19 (stessa disambiguazione mancava
per i documenti con periodo riconosciuto). Migrato da
scripts/test_issue2_destination_path.py."""

from payroll_ingest.config import Settings
from payroll_ingest.dto import (
    CompanyDTO,
    DocumentStatus,
    EmployeeDTO,
    PayrollDocumentDTO,
    PeriodDTO,
    PeriodType,
)
from payroll_ingest.orchestrator import _destination_path

SHA_A = "a" * 64
SHA_B = "b" * 64


def _unrecognized_dto() -> PayrollDocumentDTO:
    return PayrollDocumentDTO(
        company=CompanyDTO(ragione_sociale=""),
        employee=EmployeeDTO(cognome_nome="", codice_fiscale=""),
        period=PeriodDTO(mese=0, anno=0, tipo=PeriodType.ORDINARIO, label_originale=""),
        template_name="unknown",
    )


def test_needs_review_same_filename_different_hash_no_overwrite():
    settings = Settings()
    dto = _unrecognized_dto()
    path_a = _destination_path(settings, DocumentStatus.NEEDS_REVIEW, dto, "07.pdf", SHA_A)
    path_b = _destination_path(settings, DocumentStatus.NEEDS_REVIEW, dto, "07.pdf", SHA_B)
    assert path_a != path_b
    assert "non_riconosciuti" in path_a.parts
    assert "non_riconosciuti" in path_b.parts
    assert path_a.name.endswith("07.pdf")
    assert path_b.name.endswith("07.pdf")


def test_failed_same_filename_different_hash_no_overwrite():
    settings = Settings()
    dto = _unrecognized_dto()
    path_a = _destination_path(settings, DocumentStatus.FAILED, dto, "08.pdf", SHA_A)
    path_b = _destination_path(settings, DocumentStatus.FAILED, dto, "08.pdf", SHA_B)
    assert path_a != path_b


def test_recognized_period_uses_hash_prefix():
    settings = Settings()
    dto = _unrecognized_dto()
    dto.period.mese = 7
    dto.period.anno = 2025
    path = _destination_path(settings, DocumentStatus.PROCESSED, dto, "07.pdf", SHA_A)
    assert path == settings.processed_dir / "2025" / "07" / f"{SHA_A[:8]}_07.pdf"


def test_recognized_period_same_filename_different_hash_no_overwrite():
    settings = Settings()
    dto = _unrecognized_dto()
    dto.period.mese = 7
    dto.period.anno = 2025
    path_a = _destination_path(settings, DocumentStatus.PROCESSED, dto, "07.pdf", SHA_A)
    path_b = _destination_path(settings, DocumentStatus.PROCESSED, dto, "07.pdf", SHA_B)
    assert path_a != path_b
