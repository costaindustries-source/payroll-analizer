#!/usr/bin/env python3
"""Smoke test di regressione per il recognizer/parser Zucchetti.

Gira sui 6 cedolini reali di riferimento (mai versionati in git, v. .gitignore)
per verificare che riconoscimento + mapping continuino a funzionare dopo una
modifica a packages/payroll-ingest/src/payroll_ingest/templates/zucchetti.py o
extraction.py.

Uso:
    python scripts/smoke_test.py [--samples-dir docs/payroll-test]

Exit code 0 se tutti i campioni passano, 1 altrimenti (adatto a gate CI/release).
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "payroll-ingest" / "src"))

from payroll_ingest.extraction import extract_document  # noqa: E402
from payroll_ingest.templates.zucchetti import is_zucchetti_document, map_document  # noqa: E402

EXPECTED_SAMPLES = ["202112.pdf", "202208.pdf", "202313.pdf", "202409.pdf", "04.pdf", "05.pdf"]
MIN_PAY_LINES = 1


def check_sample(path: Path) -> list[str]:
    """Ritorna la lista di problemi trovati (vuota se il campione passa)."""
    problems: list[str] = []
    doc = extract_document(path)
    if not is_zucchetti_document(doc):
        problems.append("non riconosciuto come cedolino Zucchetti")
        return problems

    dto = map_document(doc)
    if not dto.company.ragione_sociale:
        problems.append("ragione_sociale non estratta")
    if not dto.employee.codice_fiscale:
        problems.append("codice_fiscale non estratto")
    if dto.period.mese == 0:
        problems.append("periodo non riconosciuto")
    if len(dto.pay_lines) < MIN_PAY_LINES:
        problems.append(f"solo {len(dto.pay_lines)} pay_lines estratte (minimo atteso {MIN_PAY_LINES})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=REPO_ROOT / "docs" / "payroll-test",
        help="Cartella con i cedolini di riferimento (default: docs/payroll-test)",
    )
    args = parser.parse_args()

    if not args.samples_dir.is_dir():
        print(f"ERRORE: cartella campioni non trovata: {args.samples_dir}")
        print("I cedolini di riferimento non sono versionati in git (v. .gitignore):")
        print("vanno presenti localmente su ogni ambiente (Ubuntu dev e Debian) per poter fare smoke test.")
        return 1

    missing = [name for name in EXPECTED_SAMPLES if not (args.samples_dir / name).is_file()]
    if missing:
        print(f"ERRORE: campioni mancanti in {args.samples_dir}: {missing}")
        return 1

    failures = 0
    for name in EXPECTED_SAMPLES:
        path = args.samples_dir / name
        problems = check_sample(path)
        if problems:
            failures += 1
            print(f"FAIL {name}: {'; '.join(problems)}")
        else:
            print(f"OK   {name}")

    print()
    if failures:
        print(f"{failures}/{len(EXPECTED_SAMPLES)} campioni falliti.")
        return 1
    print(f"Tutti i {len(EXPECTED_SAMPLES)} campioni ok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
