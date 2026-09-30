"""Primitive per leggere le tabelle a celle dei cedolini dalla geometria di
rendering (RawPage.geo_words / RawPage.vlines, da PyMuPDF).

Perche' non le x delle Word di pdfplumber: sui PDF Win2PDF tutti i caratteri
di una parola condividono l'origine del testo, che non e' dove il glifo viene
disegnato (verificato: valori sfasati di 20-40 pt rispetto alla cella). Le
tabelle di riepilogo dei Copernico hanno inoltre colonne di larghezza non
fissa e celle vuote anche in mezzo (Imposta a Debito/Credito sono mutuamente
esclusive), quindi ne' soglie x fisse ne' l'ordine dei valori bastano.

Qui ogni importo viene assegnato alla cella che lo contiene, delimitata dai
bordi verticali realmente disegnati nel PDF. Ogni lettura e' validata (numero
di celle atteso, etichette di intestazione nella cella giusta, al massimo un
importo per cella): se qualcosa non torna ritorna None e il chiamante usa il
suo fallback, invece di assegnare un importo alla colonna sbagliata."""

import re
from dataclasses import dataclass
from decimal import Decimal

from payroll_ingest.extraction import Word
from payroll_ingest.normalize import parse_amount

EDGE_CLUSTER_TOLERANCE = 3.0
MIN_CELL_WIDTH = 15.0
LINE_CLUSTER_TOLERANCE = 3.0
# Distanza verticale massima tra riga di intestazione e riga dei valori.
MAX_HEADER_TO_VALUES_DY = 30.0


@dataclass
class GeoLine:
    y: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def geo_lines(words: list[Word]) -> list[GeoLine]:
    """Raggruppa le parole in righe per centro verticale, dall'alto in basso."""
    ordered = sorted(words, key=lambda w: (w.top + w.bottom) / 2)
    lines: list[list[Word]] = []
    means: list[float] = []
    for w in ordered:
        y = (w.top + w.bottom) / 2
        if lines and abs(y - means[-1]) <= LINE_CLUSTER_TOLERANCE:
            lines[-1].append(w)
            means[-1] = sum((x.top + x.bottom) / 2 for x in lines[-1]) / len(lines[-1])
        else:
            lines.append([w])
            means.append(y)
    return [GeoLine(y=m, words=sorted(ws, key=lambda w: w.x0)) for m, ws in zip(means, lines, strict=True)]


def cell_bounds(vlines, y: float, min_x: float = 0.0) -> list[tuple[float, float]]:
    """Celle (x_sinistra, x_destra) della tabella che attraversa l'ordinata
    ``y``, dai bordi verticali che la coprono. I bordi doppi (linee a <3pt)
    vengono fusi. Le celle piu' strette di MIN_CELL_WIDTH sono scartate."""
    xs = sorted(v.x for v in vlines if v.top <= y <= v.bottom and v.x >= min_x)
    edges: list[list[float]] = []
    for x in xs:
        if edges and x - edges[-1][-1] <= EDGE_CLUSTER_TOLERANCE:
            edges[-1].append(x)
        else:
            edges.append([x])
    positions = [sum(e) / len(e) for e in edges]
    return [(a, b) for a, b in zip(positions, positions[1:], strict=False) if b - a >= MIN_CELL_WIDTH]


def cell_index(bounds: list[tuple[float, float]], word: Word) -> int | None:
    center = (word.x0 + word.x1) / 2
    for i, (left, right) in enumerate(bounds):
        if left <= center < right:
            return i
    return None


def find_lines(lines: list[GeoLine], pattern: re.Pattern[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if pattern.search(line.text)]


def value_line_below(lines: list[GeoLine], header_idx: int) -> GeoLine | None:
    """Riga immediatamente sotto l'intestazione, se contiene almeno un importo.
    Su alcune pagine la tabella compare come copia vuota (solo intestazione)."""
    if header_idx + 1 >= len(lines):
        return None
    header, below = lines[header_idx], lines[header_idx + 1]
    if not 0 < below.y - header.y <= MAX_HEADER_TO_VALUES_DY:
        return None
    if not any(parse_amount(w.text) is not None for w in below.words):
        return None
    return below


def read_header_value_row(
    vlines, header: GeoLine, values: GeoLine, header_patterns: list[re.Pattern[str]]
) -> list[Decimal | None] | None:
    """Legge una riga di valori sotto una riga di intestazione a N celle.
    ``header_patterns[i]`` deve comparire nel testo di intestazione della
    cella i: e' cio' che garantisce che la colonna sia quella attesa."""
    bounds = cell_bounds(vlines, values.y)
    if len(bounds) != len(header_patterns):
        return None
    for i, pattern in enumerate(header_patterns):
        header_text = " ".join(w.text for w in header.words if cell_index(bounds, w) == i)
        if not pattern.search(header_text):
            return None
    result: list[Decimal | None] = [None] * len(bounds)
    for w in values.words:
        amount = parse_amount(w.text)
        if amount is None:
            continue
        idx = cell_index(bounds, w)
        if idx is None or result[idx] is not None:
            return None
        result[idx] = amount
    return result
