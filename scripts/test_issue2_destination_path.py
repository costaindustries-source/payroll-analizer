#!/usr/bin/env python3
"""Verifica ad-hoc per issue GH #2 (file-mover sovrascrive silenziosamente
processed/non_riconosciuti/<nome> su reprocessing con contenuto diverso).

Uso: uv run python scripts/test_issue2_destination_path.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "payroll-ingest" / "src"))

from payroll_ingest.config import Settings  # noqa: E402
from payroll_ingest.dto import DocumentStatus, PayrollDocumentDTO, CompanyDTO, EmployeeDTO, PeriodDTO, PeriodType  # noqa: E402
from payroll_ingest.orchestrator import _destination_path  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"{status} {label}" + (f" ({detail})" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def unrecognized_dto() -> PayrollDocumentDTO:
    return PayrollDocumentDTO(
        company=CompanyDTO(ragione_sociale=""),
        employee=EmployeeDTO(cognome_nome="", codice_fiscale=""),
        period=PeriodDTO(mese=0, anno=0, tipo=PeriodType.ORDINARIO, label_originale=""),
        template_name="unknown",
    )


settings = Settings()
dto = unrecognized_dto()

# --- Caso 1: due tentativi NEEDS_REVIEW dello stesso filename, hash diversi ---
sha_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
sha_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
path_a = _destination_path(settings, DocumentStatus.NEEDS_REVIEW, dto, "07.pdf", sha_a)
path_b = _destination_path(settings, DocumentStatus.NEEDS_REVIEW, dto, "07.pdf", sha_b)
check("caso 1: i due path 'non_riconosciuti' sono diversi (niente sovrascrittura)", path_a != path_b, f"{path_a} vs {path_b}")
check("caso 1: entrambi dentro 'non_riconosciuti'", "non_riconosciuti" in path_a.parts and "non_riconosciuti" in path_b.parts)
check("caso 1: entrambi riportano il nome file originale", path_a.name.endswith("07.pdf") and path_b.name.endswith("07.pdf"))

# --- Caso 2: due tentativi FAILED dello stesso filename, hash diversi ---
path_fa = _destination_path(settings, DocumentStatus.FAILED, dto, "08.pdf", sha_a)
path_fb = _destination_path(settings, DocumentStatus.FAILED, dto, "08.pdf", sha_b)
check("caso 2: i due path 'error' sono diversi (niente sovrascrittura)", path_fa != path_fb, f"{path_fa} vs {path_fb}")

# --- Caso 3: documento con periodo riconosciuto non cambia comportamento (nessuna regressione) ---
dto_ok = unrecognized_dto()
dto_ok.period.mese = 7
dto_ok.period.anno = 2025
path_ok = _destination_path(settings, DocumentStatus.PROCESSED, dto_ok, "07.pdf", sha_a)
check(
    "caso 3: documento riconosciuto usa ancora anno/mese senza prefisso hash",
    path_ok == settings.processed_dir / "2025" / "07" / "07.pdf",
    str(path_ok),
)

print()
if failures:
    print(f"{len(failures)} controlli falliti: {failures}")
    sys.exit(1)
print("Tutti i controlli passati.")
