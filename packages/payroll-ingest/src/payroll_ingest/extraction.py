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

# Alcuni PDF (font Win2PDF senza FontBBox/width, v. docs/PIANO_TECNICO_NEW_TEMPLATES.md
# §3) hanno larghezza di avanzamento nulla: tutti i frammenti di una parola condividono
# lo stesso x0 (± ~0.3pt), e l'ordinamento per posizione di extract_words() produce
# anagrammi (anche sulle cifre degli importi). Verificato empiricamente sui 12 file
# Win2PDF noti (2018-03 -> 2019-01): frazione di coppie a x0 uguale ~0.77-0.79, contro
# 0.0 sui PDF puliti dello stesso layout e ~0.05 sui cedolini Zucchetti di riferimento.
SCRAMBLE_X0_TOLERANCE = 0.5
SCRAMBLE_FRACTION_THRESHOLD = 0.20
# Soglia di salto x0 per separare due parole ricostruite (v. _reconstruct_words):
# i frammenti della STESSA parola condividono l'x0 di inizio parola (delta < 1pt nei
# campioni verificati), mentre il passaggio a una parola successiva comporta uno
# scarto ben maggiore (prossima colonna/parola sulla pagina).
WORD_X0_JUMP_TOLERANCE = 3.0


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
    recovered_from_scramble: bool = False


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


def _is_scrambled_page(chars: list[dict]) -> bool:
    """Rileva il font Win2PDF a avanzamento zero (v. costanti SCRAMBLE_*):
    frazione di coppie di caratteri consecutivi nello stream (``page.chars``,
    gia' nell'ordine di disegno originale) che condividono lo stesso x0 pur
    essendo caratteri distinti. Un font con metriche corrette non produce mai
    questa coincidenza sistematica; un font a larghezza nulla la produce per
    ogni carattere successivo al primo di ciascuna parola."""
    if len(chars) < 2:
        return False
    same_x0_pairs = sum(
        1
        for a, b in zip(chars, chars[1:])
        if a["text"] != b["text"] and abs(a["x0"] - b["x0"]) <= SCRAMBLE_X0_TOLERANCE
    )
    return (same_x0_pairs / (len(chars) - 1)) > SCRAMBLE_FRACTION_THRESHOLD


def _reconstruct_words(chars: list[dict]) -> list[Word]:
    """Ricostruisce le parole da ``page.chars`` per le pagine con font a
    avanzamento zero, dove l'ordine di disegno (gia' corretto, a differenza
    dell'ordinamento per posizione di extract_words()) e' l'unico segnale
    affidabile: i caratteri di una stessa parola condividono l'x0 di inizio
    parola (entro WORD_X0_JUMP_TOLERANCE), mentre una parola nuova comporta uno
    scarto x0 maggiore o un cambio di riga. Il testo e' la concatenazione dei
    caratteri nell'ordine di stream (nessuno spazio inserito: gli spazi reali
    sono gia' caratteri a se stanti nello stream); l'x0 della parola e' il
    minimo dei frammenti, cosi' come previsto per l'assegnazione a colonna."""
    words: list[Word] = []
    current: Word | None = None
    for c in chars:
        text, x0, x1, top, bottom = c["text"], c["x0"], c["x1"], c["top"], c["bottom"]
        if (
            current is None
            or abs(top - current.top) > ROW_CLUSTER_TOLERANCE
            or abs(x0 - current.x0) > WORD_X0_JUMP_TOLERANCE
        ):
            current = Word(text=text, x0=x0, x1=x1, top=top, bottom=bottom)
            words.append(current)
        else:
            current.text += text
            current.x0 = min(current.x0, x0)
            current.x1 = max(current.x1, x1)
            current.bottom = max(current.bottom, bottom)
    return words


def extract_page(page: pdfplumber.page.Page) -> RawPage:
    recovered = _is_scrambled_page(page.chars)
    if recovered:
        chars = [c for c in page.chars if c["x1"] > SIDEBAR_MAX_X1]
        words = _reconstruct_words(chars)
    else:
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
    return RawPage(
        words=words,
        rows=rows,
        full_text=full_text,
        width=page.width,
        height=page.height,
        recovered_from_scramble=recovered,
    )


def extract_document(path: Path, ocr_used: bool = False) -> RawExtractedDocument:
    with pdfplumber.open(path) as pdf:
        pages = [extract_page(page) for page in pdf.pages]
    return RawExtractedDocument(source_path=path, pages=pages, ocr_used=ocr_used)
