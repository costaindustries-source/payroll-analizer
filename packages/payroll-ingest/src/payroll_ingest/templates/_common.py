"""Helper generici condivisi tra i moduli template (non specifici di un layout).

Estratto da ``zucchetti.py`` in occasione dell'introduzione del registry
multi-template (v. docs/PIANO_TECNICO_NEW_TEMPLATES.md §4): stesso codice,
stesso comportamento, solo spostato qui perche' ogni nuovo template (Copernico,
SAP HR, ...) deve validare CF/IBAN con lo stesso standard nazionale/ISO e
riconoscere gli stessi marker di formattazione importi, senza duplicarli.
"""

from decimal import Decimal

from payroll_ingest.extraction import Word
from payroll_ingest.normalize import normalize_label, parse_amount

UNIT_TOKENS = {"GG", "ORE", "%"}
# "{" e' la resa vista dal glitch di font per la parentesi aperta di un importo
# negativo su alcuni cedolini Zucchetti (v. issue GH #3, 07.pdf/08.pdf/202201.pdf).
PAREN_MARKERS = {"(", ")", "{", "}"}

# Tolleranza condivisa per il pattern label-row/value-row (v. match_column_values):
# intestazioni di colonna su una riga, valori senza etichetta sulla riga successiva,
# assegnati alla colonna il cui marker ha l'x0 piu' vicino.
COLUMN_MATCH_TOLERANCE = 60.0


def looks_like_data(text: str) -> bool:
    return text in UNIT_TOKENS or text in PAREN_MARKERS or parse_amount(text) is not None


def rows_with_numeric_value(texts: list[str]) -> list[str]:
    """Filtra le righe che contengono almeno un token con la forma di un
    importo/numero: usato per distinguere, tra le righe non riconosciute
    della sezione voci, quelle con un dato economico candidato a perdita
    reale da quelle puramente testuali (header di colonna, riga di
    intestazione periodo) - rumore innocuo che altrimenti fa scattare
    l'anomalia 'righe_non_mappate' anche quando non c'e' nessuna perdita
    (issue GH #32)."""
    return [text for text in texts if any(parse_amount(token) is not None for token in text.split())]


def first_amount(words: list[Word]) -> Decimal | None:
    for w in words:
        if w.text in PAREN_MARKERS:
            continue
        value = parse_amount(w.text)
        if value is not None:
            return abs(value)
    return None


def amount_after_label(words: list[Word], label_norm: str) -> Decimal | None:
    """Cerca il primo importo che segue (per posizione nella riga, non solo nel
    testo) la parola che completa l'etichetta cercata, invece del primo importo
    dell'intera riga. Necessario quando due blocchi logicamente distinti
    finiscono sulla stessa riga clusterizzata. ``words`` deve gia' essere
    ordinato per x0 (v. extraction._cluster_rows)."""
    acc = ""
    for idx, w in enumerate(words):
        acc = normalize_label(acc + w.text)
        if label_norm in acc:
            for later in words[idx + 1 :]:
                if later.text in PAREN_MARKERS:
                    continue
                value = parse_amount(later.text)
                if value is not None:
                    return abs(value)
            return None
    # L'etichetta non e' stata trovata scandendo parola per parola (non
    # dovrebbe succedere, dato che il chiamante ha gia' verificato un match su
    # tutta la riga): fallback prudenziale sul comportamento precedente.
    return first_amount(words)


def match_column_values(
    marker_positions: list[tuple[float, str]], value_words: list[Word], tolerance: float
) -> dict[str, Decimal]:
    """Assegna ogni importo di ``value_words`` al campo il cui marker di colonna
    (in ``marker_positions``, coppie x0/nome-campo lette dalla riga di
    intestazione) ha l'x0 piu' vicino, purche' entro ``tolerance``. Pattern
    ricorrente nei cedolini per le sotto-tabelle "intestazione colonne su una
    riga, valori senza etichetta sulla riga successiva" (es. T.F.R.,
    PROGRESSIVI)."""
    values: dict[str, Decimal] = {}
    for value_word in value_words:
        amount = parse_amount(value_word.text)
        if amount is None:
            continue
        nearest_x0, field = min(marker_positions, key=lambda m: abs(m[0] - value_word.x0))
        if abs(nearest_x0 - value_word.x0) <= tolerance:
            values[field] = amount
    return values


# Tabelle ufficiali del check-digit del codice fiscale italiano (16esimo
# carattere, calcolato dai primi 15 con pesi diversi per posizione dispari/pari,
# 1-indexed).
_CF_ODD_VALUES = {
    "0": 1,
    "1": 0,
    "2": 5,
    "3": 7,
    "4": 9,
    "5": 13,
    "6": 15,
    "7": 17,
    "8": 19,
    "9": 21,
    "A": 1,
    "B": 0,
    "C": 5,
    "D": 7,
    "E": 9,
    "F": 13,
    "G": 15,
    "H": 17,
    "I": 19,
    "J": 21,
    "K": 2,
    "L": 4,
    "M": 18,
    "N": 20,
    "O": 11,
    "P": 3,
    "Q": 6,
    "R": 8,
    "S": 12,
    "T": 14,
    "U": 16,
    "V": 10,
    "W": 22,
    "X": 25,
    "Y": 24,
    "Z": 23,
}
_CF_EVEN_VALUES = {
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "A": 0,
    "B": 1,
    "C": 2,
    "D": 3,
    "E": 4,
    "F": 5,
    "G": 6,
    "H": 7,
    "I": 8,
    "J": 9,
    "K": 10,
    "L": 11,
    "M": 12,
    "N": 13,
    "O": 14,
    "P": 15,
    "Q": 16,
    "R": 17,
    "S": 18,
    "T": 19,
    "U": 20,
    "V": 21,
    "W": 22,
    "X": 23,
    "Y": 24,
    "Z": 25,
}
_CF_REMAINDER_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def codice_fiscale_checksum_valido(cf: str) -> bool:
    """Verifica il check-digit ufficiale del codice fiscale italiano (standard
    nazionale, indipendente dal template/layout del cedolino)."""
    if len(cf) != 16:
        return False
    try:
        total = sum(
            _CF_ODD_VALUES[ch] if (idx + 1) % 2 == 1 else _CF_EVEN_VALUES[ch] for idx, ch in enumerate(cf[:15])
        )
    except KeyError:
        return False
    return _CF_REMAINDER_LETTERS[total % 26] == cf[15]


def iban_mod97_valid(iban: str) -> bool:
    """Checksum ISO 7064 mod 97-10 di un IBAN (standard, indipendente dal
    template/layout del cedolino)."""
    rearranged = iban[4:] + iban[:4]
    try:
        digits = "".join(str(int(ch, 36)) for ch in rearranged)
    except ValueError:
        return False
    return int(digits) % 97 == 1
