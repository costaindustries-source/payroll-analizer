#!/usr/bin/env python3
"""Verifica ad-hoc per issue GH #4 (glitch font Zucchetti Z->2 su codici causale,
O->0 su IBAN) e issue GH #5 (carattere spurio anteposto al codice causale). Usa
Row/Word sintetici (nessun cedolino reale, nessun dato personale) perche' i
campioni reali sono gitignored e non presenti su questa sandbox.

Uso: uv run python scripts/test_issue4_font_corruption.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "payroll-ingest" / "src"))

from payroll_ingest.extraction import Row, Word  # noqa: E402
from payroll_ingest.templates import zucchetti as z  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"{status} {label}" + (f" ({detail})" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def word(text: str, x0: float) -> Word:
    return Word(text=text, x0=x0, x1=x0 + len(text) * 5, top=100.0, bottom=110.0)


# --- Caso 1a: codice corrotto grammaticalmente impossibile (2P9960 da ZP9960) ---
row_a = Row(top=100.0, words=[word("2P9960", 30), word("Arrotond.", 60), word("mese", 100), word("pr.", 130)])
line_a = z._parse_causale_row(row_a)
check("caso 1a: riga con '2P9960' viene comunque mappata (non persa)", line_a is not None)
if line_a is not None:
    payline, correction = line_a
    check("caso 1a: codice corretto in 'ZP9960'", payline.codice == "ZP9960", payline.codice)
    check(
        "caso 1a: correzione riportata per l'anomalia",
        correction == ("2P9960", "ZP9960", "font_digit_lettera"),
        str(correction),
    )

# --- Caso 1b: codice corrotto che combacia per caso con _CODE_RE (Z00020 -> 200020) ---
row_b = Row(top=110.0, words=[word("200020", 30), word("Retribuzione", 60), word("Ordinaria", 110)])
line_b = z._parse_causale_row(row_b)
check("caso 1b: riga con '200020' viene mappata", line_b is not None)
if line_b is not None:
    payline_b, correction_b = line_b
    check(
        "caso 1b: codice NON alterato silenziosamente (nessun checksum disponibile)",
        payline_b.codice == "200020",
        payline_b.codice,
    )
    check("caso 1b: nessuna 'correzione' automatica riportata (solo sospetto, gestito a livello doc)", correction_b is None)
check(
    "caso 1b: '200020' e' riconosciuto come pattern sospetto (2 + 5 cifre)",
    bool(z._SUSPECT_LEADING_2_RE.match("200020")),
)

# --- Caso 1c: codice genuinamente valido non deve essere toccato ---
codice_valido, tipo_correzione_valido = z._recover_causale_code("F02000")
check("caso 1c: codice valido 'F02000' non modificato", codice_valido == "F02000" and tipo_correzione_valido is None)

# --- Caso 1d: carattere spurio anteposto al codice (issue GH #5, '\F03020' su 07.pdf) ---
row_d = Row(top=120.0, words=[word("\\F03020", 30), word("Ritenute", 60), word("IRPEF", 100), word("1.560,21", 460)])
line_d = z._parse_causale_row(row_d)
check("caso 1d: riga con '\\F03020' viene comunque mappata (non persa)", line_d is not None)
if line_d is not None:
    payline_d, correction_d = line_d
    check("caso 1d: codice corretto in 'F03020'", payline_d.codice == "F03020", payline_d.codice)
    check(
        "caso 1d: correzione riportata come 'prefisso_spurio'",
        correction_d == ("\\F03020", "F03020", "prefisso_spurio"),
        str(correction_d),
    )

# --- Caso 2: IBAN con CIN corrotto O->0 (la manifestazione confermata nell'issue),
# verificato via checksum mod-97 ---
bban = "O0542811101000000123456"  # CIN 'O' + 5 ABI + 5 CAB + 12 conto
iban_valido = None
for cc in range(100):
    candidate = f"IT{cc:02d}{bban}"
    if z._iban_mod97_valid(candidate):
        iban_valido = candidate
        break
check("setup: IBAN sintetico di riferimento e' checksum-valido", iban_valido is not None, str(iban_valido))
assert iban_valido is not None

cin_pos = 4
assert iban_valido[cin_pos] == "O"
iban_corrotto = iban_valido[:cin_pos] + "0" + iban_valido[cin_pos + 1 :]
recovered, was_corrected = z._recover_iban(iban_corrotto)
check("caso 2: IBAN con CIN='0' viene corretto", was_corrected, f"input={iban_corrotto!r}")
check("caso 2: IBAN corretto torna uguale all'originale", recovered == iban_valido, f"got={recovered!r}")

# --- Caso 2b: IBAN con cifra non recuperabile (nessun candidato passa il checksum) ---
iban_non_recuperabile = "IT60" + "5" + "0542811101000000123456"[1:]  # CIN '5' a caso, quasi certo non-checksum-valido
recovered_bad, was_corrected_bad = z._recover_iban(iban_non_recuperabile)
check(
    "caso 2b: IBAN non recuperabile resta invariato (nessuna correzione forzata)",
    not was_corrected_bad and recovered_bad == iban_non_recuperabile,
)

# --- Caso 2c: IBAN gia' valido non deve essere toccato ---
recovered_ok, was_corrected_ok = z._recover_iban(iban_valido)
check("caso 2c: IBAN gia' valido non modificato", recovered_ok == iban_valido and not was_corrected_ok)

print()
if failures:
    print(f"{len(failures)} controlli falliti: {failures}")
    sys.exit(1)
print("Tutti i controlli passati.")
