"""Estrazione posizionale del testo dai cedolini.

Il PDF Zucchetti analizzato contiene una striscia decorativa verticale (marchio
"ZUCCHETTI" e testo di boilerplate) lungo il margine sinistro (x0 approssimativamente
tra 17 e 24 pt). ``extract_text()`` di pdfplumber mescola questa striscia con le righe
dati quando i valori di ``top`` sono vicini, producendo testo illeggibile.
La soluzione verificata sui 6 campioni: lavorare a livello di parola (bounding box),
escludere le parole interamente contenute nella fascia della sidebar e raggruppare
per riga tramite clustering sul valore ``top`` con tolleranza ridotta.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

SIDEBAR_MAX_X1 = 25.0
ROW_CLUSTER_TOLERANCE = 3.0
WORD_X_TOLERANCE = 1.5
WORD_Y_TOLERANCE = 1.5


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class Row:
    top: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class RawPage:
    words: list[Word]
    rows: list[Row]
    full_text: str
    width: float
    height: float


@dataclass
class RawExtractedDocument:
    source_path: Path
    pages: list[RawPage]
    ocr_used: bool = False
    unmapped_rows: list[str] = field(default_factory=list)

    @property
    def first_page(self) -> RawPage:
        return self.pages[0]


def _cluster_rows(words: list[Word]) -> list[Row]:
    # Confronto con l'ancora (top della prima parola della riga), non con l'ultima
    # parola vista: in questo layout diversi sotto-blocchi (TFR/ratei/totali)
    # condividono un ritmo verticale molto stretto, e un confronto "a catena" con
    # l'ultima parola fondrebbe righe distinte tramite una parola-ponte intermedia
    # (es. il valore di "TOTALE TRATTENUTE" e la riga "Ferie" successiva finiscono
    # a <3pt l'uno dall'altro pur essendo due dati semanticamente diversi). Il
    # confronto con l'ancora e' quindi la scelta corretta per questo template,
    # anche se in teoria puo' spezzare una riga isolata il cui top deriva di piu'
    # di ROW_CLUSTER_TOLERANCE tra prima e ultima parola (caso raro e verificato
    # innocuo sui campioni reali, dato che nessun campo viene letto da quelle righe).
    rows: list[Row] = []
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and abs(w.top - rows[-1].top) <= ROW_CLUSTER_TOLERANCE:
            rows[-1].words.append(w)
        else:
            rows.append(Row(top=w.top, words=[w]))
    for row in rows:
        row.words.sort(key=lambda w: w.x0)
    return rows


def extract_page(page: pdfplumber.page.Page) -> RawPage:
    # y_tolerance esplicito: col default (3pt) pdfplumber a volte fonde due righe
    # dati distinte ~10pt apart in un'unica "linea" quando condividono le stesse
    # colonne x, producendo parole di un solo carattere e testo illeggibile.
    raw_words = page.extract_words(
        x_tolerance=WORD_X_TOLERANCE, y_tolerance=WORD_Y_TOLERANCE, keep_blank_chars=False
    )
    words = [
        Word(text=w["text"], x0=w["x0"], x1=w["x1"], top=w["top"], bottom=w["bottom"])
        for w in raw_words
        if w["x1"] > SIDEBAR_MAX_X1
    ]
    rows = _cluster_rows(words)
    full_text = "\n".join(row.text for row in rows)
    return RawPage(words=words, rows=rows, full_text=full_text, width=page.width, height=page.height)


def extract_document(path: Path, ocr_used: bool = False) -> RawExtractedDocument:
    with pdfplumber.open(path) as pdf:
        pages = [extract_page(page) for page in pdf.pages]
    return RawExtractedDocument(source_path=path, pages=pages, ocr_used=ocr_used)
