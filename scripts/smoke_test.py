#!/usr/bin/env python3
"""Smoke test di regressione per il registry multi-template (Zucchetti,
Copernico, SAP HR).

Gira su 13 cedolini reali di riferimento (mai versionati in git, v.
.gitignore) per verificare che riconoscimento + mapping continuino a
funzionare dopo una modifica a un modulo in
packages/payroll-ingest/src/payroll_ingest/templates/ o a extraction.py.

Uso:
    python scripts/smoke_test.py

Exit code 0 se tutti i campioni passano, 1 altrimenti (adatto a gate CI/release).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "payroll-ingest" / "src"))

from payroll_ingest.extraction import extract_document  # noqa: E402
from payroll_ingest.templates import find_template  # noqa: E402
from payroll_ingest.templates._common import iban_mod97_valid  # noqa: E402

ZUCCHETTI_DIR = REPO_ROOT / "docs" / "payroll-test"
NEW_TEMPLATES_DIR = REPO_ROOT / "docs" / "new-templates"

# (cartella campioni, filename, template atteso, mese atteso, anno atteso)
EXPECTED_SAMPLES = [
    (ZUCCHETTI_DIR, "202112.pdf", "zucchetti_standard", None, None),
    (ZUCCHETTI_DIR, "202208.pdf", "zucchetti_standard", None, None),
    (ZUCCHETTI_DIR, "202313.pdf", "zucchetti_standard", None, None),
    (ZUCCHETTI_DIR, "202409.pdf", "zucchetti_standard", None, None),
    (ZUCCHETTI_DIR, "04.pdf", "zucchetti_standard", None, None),
    (ZUCCHETTI_DIR, "05.pdf", "zucchetti_standard", None, None),
    # Layout A / Copernico: un ordinario e una tredicesima PDFsharp puliti,
    # un Win2PDF a pagina singola e uno multipagina (v. piano §8).
    (NEW_TEMPLATES_DIR / "2016", "201610.pdf", "copernico_paghe", 10, 2016),
    (NEW_TEMPLATES_DIR / "2016", "201613.pdf", "copernico_paghe", 12, 2016),
    (NEW_TEMPLATES_DIR / "2018", "201804.pdf", "copernico_paghe", 4, 2018),
    (NEW_TEMPLATES_DIR / "2018", "201811.pdf", "copernico_paghe", 11, 2018),
    # Layout B / SAP HR: il primo file del layout, un ordinario 2020 e la
    # tredicesima 2020 (periodo interno 12/2020, v. piano §6).
    (NEW_TEMPLATES_DIR / "2019", "201902.pdf", "sap_hr", 2, 2019),
    (NEW_TEMPLATES_DIR / "2020", "202001.pdf", "sap_hr", 1, 2020),
    (NEW_TEMPLATES_DIR / "2020", "202013.pdf", "sap_hr", 12, 2020),
]
MIN_PAY_LINES = 1


def check_sample(path: Path, template_atteso: str, mese_atteso: int | None, anno_atteso: int | None) -> list[str]:
    """Ritorna la lista di problemi trovati (vuota se il campione passa)."""
    problems: list[str] = []
    doc = extract_document(path)
    spec = find_template(doc)
    if spec is None:
        problems.append("nessun template riconosciuto")
        return problems
    if spec.name != template_atteso:
        problems.append(f"template atteso {template_atteso!r}, trovato {spec.name!r}")
        return problems

    dto = spec.map(doc)
    if not dto.company.ragione_sociale:
        problems.append("ragione_sociale non estratta")
    if not dto.employee.codice_fiscale:
        problems.append("codice_fiscale non estratto")
    if mese_atteso is not None and dto.period.mese != mese_atteso:
        problems.append(f"mese atteso {mese_atteso}, trovato {dto.period.mese}")
    if anno_atteso is not None and dto.period.anno != anno_atteso:
        problems.append(f"anno atteso {anno_atteso}, trovato {dto.period.anno}")
    if mese_atteso is None and dto.period.mese == 0:
        problems.append("periodo non riconosciuto")
    if not dto.totals or dto.totals.netto_mese is None:
        problems.append("netto_mese non estratto")
    if not dto.totals or not dto.totals.iban:
        problems.append("iban non estratto")
    elif not iban_mod97_valid(dto.totals.iban):
        problems.append("iban con checksum mod-97 non valido")
    if len(dto.pay_lines) < MIN_PAY_LINES:
        problems.append(f"solo {len(dto.pay_lines)} pay_lines estratte (minimo atteso {MIN_PAY_LINES})")
    return problems


def main() -> int:
    missing_dirs = sorted({str(d) for d, *_ in EXPECTED_SAMPLES if not d.is_dir()})
    if missing_dirs:
        print("ERRORE: cartelle campioni non trovate:")
        for d in missing_dirs:
            print(f"  {d}")
        print(
            "I cedolini di riferimento non sono versionati in git (v. .gitignore): "
            "vanno presenti localmente su ogni ambiente per poter fare smoke test."
        )
        return 1

    missing = [
        str(d / name) for d, name, *_ in EXPECTED_SAMPLES if not (d / name).is_file()
    ]
    if missing:
        print(f"ERRORE: campioni mancanti: {missing}")
        return 1

    failures = 0
    for samples_dir, name, template_atteso, mese_atteso, anno_atteso in EXPECTED_SAMPLES:
        path = samples_dir / name
        problems = check_sample(path, template_atteso, mese_atteso, anno_atteso)
        if problems:
            failures += 1
            print(f"FAIL {name} [{template_atteso}]: {'; '.join(problems)}")
        else:
            print(f"OK   {name} [{template_atteso}]")

    print()
    if failures:
        print(f"{failures}/{len(EXPECTED_SAMPLES)} campioni falliti.")
        return 1
    print(f"Tutti i {len(EXPECTED_SAMPLES)} campioni ok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
