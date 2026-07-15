#!/usr/bin/env python3
"""Gate di coverage PER FILE (non solo aggregato): `coverage report
--fail-under` valuta solo il totale, quindi un file scoperto puo' nascondersi
dietro alla media alta di altri file. Va lanciato DOPO `pytest --cov` (legge
i dati gia' raccolti da `coverage.py` nel file `.coverage`), fallisce con
exit 1 e la lista dei file sotto soglia se qualcuno e' < THRESHOLD.

Uso: uv run python scripts/check_coverage.py
"""

import sys

from coverage import Coverage

THRESHOLD = 80.0


def main() -> int:
    cov = Coverage()
    cov.load()

    data = cov.get_data()
    below: list[tuple[str, float]] = []

    for path in sorted(data.measured_files()):
        _, statements, _, missing, _ = cov.analysis2(path)
        if not statements:
            continue
        percent = 100.0 * (len(statements) - len(missing)) / len(statements)
        if percent < THRESHOLD:
            below.append((path, percent))

    if below:
        print(f"File sotto la soglia di coverage per-file ({THRESHOLD:.0f}%):")
        for path, percent in below:
            print(f"  {percent:5.1f}%  {path}")
        return 1

    print(f"Tutti i file misurati sono >= {THRESHOLD:.0f}% di coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
