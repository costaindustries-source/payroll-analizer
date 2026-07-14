import re
from datetime import date
from decimal import Decimal, InvalidOperation

_NUMBER_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+|-?\d+")
_MONTHS_IT = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def normalize_label(text: str) -> str:
    """Normalizza un'etichetta per il confronto, indipendentemente da spazi e
    dal glitch di encoding del font che nell'header decodifica lo spazio come 's'
    (rimuovendo 's' da entrambi i lati del confronto l'abbinamento resta corretto).
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", text).lower()
    return cleaned.replace("s", "")


def parse_amount(token: str) -> Decimal | None:
    """Converte un importo in formato italiano ('1.234,56', '(128,00)') in Decimal.
    Le parentesi indicano un valore negativo (trattenuta). La parentesi aperta e
    chiusa sono valutate indipendentemente (non richiedono la coppia): su alcuni
    cedolini con glitch di font piu' esteso (v. issue GH #3) la ')' di chiusura
    resta leggibile ma fusa nello stesso token dell'importo senza spazio (es.
    '297,10)'), mentre la '(' di apertura decodifica come '{' in un token a se'."""
    token = token.strip()
    negative = False
    if token.startswith("(") or token.startswith("{"):
        negative = True
        token = token[1:]
    if token.endswith(")"):
        negative = True
        token = token[:-1]
    token = token.strip().replace(".", "").replace(",", ".")
    try:
        value = Decimal(token)
    except InvalidOperation:
        return None
    return -value if negative else value


def find_amounts(text: str) -> list[str]:
    return _NUMBER_RE.findall(text)


def parse_italian_month_year(text: str) -> tuple[int, int] | None:
    """Estrae (mese, anno) da un testo come 'Agosto 2022' o 'Dicembre 2023 AGG.'."""
    match = re.search(r"([A-Za-zàèéìòù]+)\s+(\d{4})", text)
    if not match:
        return None
    month_name = match.group(1).lower()
    month = _MONTHS_IT.get(month_name)
    if month is None:
        return None
    return month, int(match.group(2))


def parse_date_ddmmyyyy(text: str) -> date | None:
    match = re.search(r"(\d{2})-(\d{2})-(\d{4})", text)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
