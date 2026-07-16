"""Template per i cedolini Zucchetti (verificato su ELBA Compagnia di Assicurazioni
2021-2022 e REVO Insurance 2023-2026). Il layout a colonne (IMPORTO BASE / RIFERIMENTO /
TRATTENUTE / COMPETENZE) e i marker di riga sono stabili tra i due datori: cambia solo
il contenuto (azienda/indirizzo), non la struttura, quindi un solo profilo di template
gestisce entrambi i datori tramite riconoscimento del contenuto, non del layout.
"""

import re
from decimal import Decimal

from payroll_ingest.dto import (
    AnomalyDTO,
    AnomalySeverity,
    CompanyDTO,
    DataClassification,
    EmployeeDTO,
    LeaveBalanceDTO,
    PayLineCategory,
    PayLineDTO,
    PayrollDocumentDTO,
    PayrollTotalsDTO,
    PeriodDTO,
    PeriodType,
    TaxDTO,
    TfrDTO,
)
from payroll_ingest.extraction import RawExtractedDocument, Row, Word
from payroll_ingest.normalize import (
    normalize_label,
    parse_amount,
    parse_date_ddmmyyyy,
    parse_italian_month_year,
)
from payroll_ingest.templates._common import (
    COLUMN_MATCH_TOLERANCE as _TFR_COLUMN_MATCH_TOLERANCE,
    PAREN_MARKERS as _PAREN_MARKERS,
    UNIT_TOKENS,
    amount_after_label as _amount_after_label,
    codice_fiscale_checksum_valido as _codice_fiscale_checksum_valido,
    first_amount as _first_amount,
    iban_mod97_valid as _iban_mod97_valid,
    looks_like_data as _looks_like_data,
    match_column_values,
)
from payroll_ingest.templates._spec import TemplateSpec

TEMPLATE_NAME = "zucchetti_standard"
PARSER_VERSION = "1.0.0"

_CODE_RE = re.compile(r"^[A-Z]{0,2}\d{4,6}$")
# Riga fatta di 1-2 sole cifre isolate nella sezione voci (osservato su
# 202201.pdf, v. issue GH #6): troppo corta per essere un codice causale
# plausibile (_CODE_RE richiede 4-6 cifre) e priva di qualunque contenuto
# testuale, a differenza delle vere righe di continuazione (es. "MBO",
# "Riferimento anno 2020/2021", v. issue GH #7/#8) che sono sempre parole.
# Rumore di estrazione/OCR: va scartato, non salvato ne' come nota ne' come
# anomalia.
_NOISE_ROW_RE = re.compile(r"^\d{1,2}$")
# Etichette di titolo-sezione stampate come riga a se stante, senza alcun dato
# numerico accanto, sui cedolini a piu' pagine dove i valori della sezione
# CONGUAGLIO/PROGRESSIVI/T.F.R. sono su un'altra pagina (v. issue GH #9/#11,
# osservato su 202212.pdf): a differenza di una vera riga di continuazione
# (es. "MBO", "Riferimento anno 2020/2021", issue GH #7/#8), qui non c'e'
# alcun contenuto informativo da agganciare alla voce precedente, e' puro
# boilerplate di layout ripetuto identico su ogni cedolino (anche quelli senza
# alcun conguaglio). Confronto per uguaglianza esatta (non substring) sul testo
# normalizzato dell'INTERA riga, cosi' da non rischiare di escludere una riga
# dati legittima che contenga una di queste parole assieme ad altro.
_BARE_SECTION_LABELS = {normalize_label(t) for t in ("CONGUAGLIO", "PROGRESSIVI", "T.F.R.")}
_COMPANY_CODE_ROW_RE = re.compile(r"^(\d{6})\s+([A-Z].{5,})$")
_ADDRESS_ROW_RE = re.compile(r"^(.*?)\s+Aut\.\s*(\S+)$")
_CAP_CITY_ROW_RE = re.compile(r"^(\d{5})\s+([A-Z].+\([A-Z]{2}\))$")
_DEL_SEDE_ROW_RE = re.compile(r"Del\s+(\S+)\s+Sede\s+(\S+)")
_COMPANY_CF_ROW_RE = re.compile(r"^(\d{11})\s+(\S+/\d{2})\s+(\S+/\d{2})$")
_EMPLOYEE_ROW_RE = re.compile(r"^(\d{7})\s+([A-ZÀ-Ü' ]+?)\s+([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])$")
_TWO_DATES_ROW_RE = re.compile(r"^(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})$")

_HEADER_MAX_TOP = 260.0

IMPORTO_BASE_MIN = 200.0
RIFERIMENTO_MIN = 345.0
TRATTENUTE_MIN = 445.0
COMPETENZE_MIN = 513.0

_TFR_BOUNDARY_LABEL = normalize_label("Retribuzione utile T.F.R.")

_CAUSALE_KEYWORDS: list[tuple[tuple[str, ...], PayLineCategory]] = [
    (("f.do sostegno", "contributo ivs", "contributo previp", "ctr.prev"), PayLineCategory.CONTRIBUTO),
    (("ferie godute", "perm.", "permesso"), PayLineCategory.ASSENZA),
    (
        ("ticket elettronico", "polizza rsmo", "vendita azioni", "stock options", "cassa inf"),
        PayLineCategory.BENEFIT,
    ),
    (("spese carta di credito",), PayLineCategory.RIMBORSO),
    (
        (
            "retribuzione ordinaria",
            "anticipo retribuzione",
            "anticipo festivit",
            "mensilita",
            "malattia",
            "assenza assunti",
            "premio",
            "arrotond",
        ),
        PayLineCategory.RETRIBUZIONE,
    ),
]

_TAX_CODE_FIELDS = {
    "F02000": "imponibile_irpef",
    "F02010": "irpef_lorda",
    "F02500": "detrazioni_lav_dip",
    "F03020": "ritenute_irpef",
}


def is_zucchetti_document(doc: RawExtractedDocument) -> bool:
    page = doc.first_page
    header_rows = [row for row in page.rows if row.top < 60]
    target = normalize_label("Codice Azienda Ragione Sociale")
    if any(normalize_label(row.text) == target for row in header_rows):
        return True
    # Fallback: su alcuni cedolini (osservato su periodi/font diversi da quelli
    # analizzati inizialmente) questa riga e' corrotta in modo piu' severo del
    # solito glitch spazio->'s' e non decodifica in modo riconoscibile. La riga
    # "codice azienda + ragione sociale" appena sotto resta leggibile ed e'
    # un'ancora altrettanto specifica del template (stesso pattern gia' usato in
    # _parse_header per estrarre l'azienda).
    return any(_COMPANY_CODE_ROW_RE.match(row.text) for row in header_rows)


def _column_of(x0: float) -> str:
    # TRATTENUTE e COMPETENZE condividono di fatto la stessa fascia destra: un
    # importo tra parentesi vi finisce comunque (vedi _split_amount_zone), quindi
    # qui serve solo distinguere descrizione/importo_base/riferimento dalla fascia
    # finale degli importi.
    if x0 >= TRATTENUTE_MIN:
        return "importo"
    if x0 >= RIFERIMENTO_MIN:
        return "riferimento"
    if x0 >= IMPORTO_BASE_MIN:
        return "importo_base"
    return "descrizione"


def _split_amount_zone(words: list[Word]) -> tuple[Decimal | None, Decimal | None]:
    """Un valore tra parentesi e' sempre una trattenuta, indipendentemente dalla
    colonna x in cui il tipografo Zucchetti lo visualizza (spesso coincide con la
    fascia COMPETENZE). Senza parentesi, la colonna x decide (trattenute a sinistra
    di COMPETENZE_MIN, competenze da COMPETENZE_MIN in poi). Normalmente il marker
    parentesi e' un token a se' stante (has_parens), ma su alcuni cedolini con
    glitch di font piu' esteso (v. issue GH #3) la ')' di chiusura e' fusa nel
    token dell'importo senza alcun marker separato nella riga (es. '408,00)' senza
    nessuna '(' o '{' altrove): in quel caso il segno gia' negativo restituito da
    parse_amount e' l'unico segnale disponibile."""
    has_parens = any(w.text in _PAREN_MARKERS for w in words)
    for w in words:
        if w.text in _PAREN_MARKERS:
            continue
        value = parse_amount(w.text)
        if value is None:
            continue
        if has_parens or value < 0 or w.x0 < COMPETENZE_MIN:
            return abs(value), None
        return None, value
    return None, None


def _parse_header(rows: list[Row]) -> tuple[CompanyDTO, EmployeeDTO, str | None, str | None]:
    header_rows = [r for r in rows if r.top < _HEADER_MAX_TOP]
    company = CompanyDTO(ragione_sociale="")
    employee = EmployeeDTO(cognome_nome="", codice_fiscale="")
    hire_date_str: str | None = None
    tipo_costo_text: str | None = None

    for row in header_rows:
        text = row.text
        if m := _COMPANY_CODE_ROW_RE.match(text):
            if not company.ragione_sociale:
                company.codice_azienda = m.group(1)
                company.ragione_sociale = m.group(2).strip()
            continue
        if m := _ADDRESS_ROW_RE.match(text):
            company.indirizzo = m.group(1).strip()
            company.inail_aut = m.group(2)
            continue
        if m := _CAP_CITY_ROW_RE.match(text):
            if company.indirizzo:
                company.indirizzo = f"{company.indirizzo}, {m.group(1)} {m.group(2)}"
            continue
        if m := _DEL_SEDE_ROW_RE.search(text):
            company.inail_del = m.group(1)
            company.inail_sede = m.group(2)
            continue
        if m := _COMPANY_CF_ROW_RE.match(text):
            company.posizione_inps = m.group(2)
            company.pat_inail = m.group(3)
            continue
        if m := _EMPLOYEE_ROW_RE.match(text):
            employee.matricola = m.group(1)
            employee.cognome_nome = m.group(2).strip()
            employee.codice_fiscale = m.group(3)
            continue
        if m := _TWO_DATES_ROW_RE.match(text):
            hire_date_str = m.group(2)
            continue
        if normalize_label("TipoCosto") in normalize_label(text):
            tipo_costo_text = text

    return company, employee, hire_date_str, tipo_costo_text


def _detect_period_type(tipo_costo_text: str | None, pay_lines: list[PayLineDTO]) -> PeriodType:
    # "CONGUAGLIO" e' un titolo di sezione presente su ogni cedolino (anche vuoto),
    # quindi non e' un indicatore valido: il segnale affidabile e' la suffissatura
    # "AGG." di TipoCosto oppure causali specifiche (mensilita aggiuntiva, righe
    # con codice "Cong." nella descrizione, es. F08993/F09000/F09100).
    # Nota: un semplice "AGG" in maiuscolo darebbe falso positivo su "MAGGIO";
    # serve il punto che segue il suffisso reale ("... AGG.").
    if tipo_costo_text and re.search(r"\bAGG\.", tipo_costo_text.upper()):
        return PeriodType.MENSILITA_AGGIUNTIVA
    for line in pay_lines:
        lowered = line.descrizione.lower()
        if "mensilita" in lowered:
            return PeriodType.MENSILITA_AGGIUNTIVA
        if "cong." in lowered:
            return PeriodType.CONGUAGLIO
    return PeriodType.ORDINARIO


def _classify_causale(descrizione: str) -> PayLineCategory:
    lowered = descrizione.lower()
    for keywords, category in _CAUSALE_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return category
    return PayLineCategory.ALTRO


_MAX_LEADING_MARKERS = 2

# Glitch di font Z->2 confermato su 07.pdf/08.pdf/202201.pdf (issue GH #4). Un
# codice causale Zucchetti e' sempre lettere-poi-cifre (v. _CODE_RE): un '2'
# iniziale seguito da un'altra lettera non e' quindi mai un codice valido a
# prescindere dal glitch, ed e' sicuro dedurre che quel '2' era una 'Z'. Quando
# invece il '2' iniziale e' seguito solo da cifre, il codice combacia per caso
# con _CODE_RE (0 lettere ammesse) e non e' distinguibile da un codice
# genuinamente numerico: qui NON correggiamo il valore (nessun checksum
# disponibile per validarlo, a differenza dell'IBAN), ci limitiamo a segnalarlo
# come sospetto in map_document quando nello stesso documento la corruzione e'
# gia' confermata altrove.
_CAUSALE_CORRUPT_DIGIT = "2"
_CAUSALE_CORRECT_LETTER = "Z"
_SUSPECT_LEADING_2_RE = re.compile(r"^2\d{3,5}$")

# Glitch diverso, confermato su 07.pdf (issue GH #5): un carattere spurio (es.
# '\') incollato DAVANTI a un codice altrimenti valido, sullo stesso token (non
# un marker separato: v. _leading_code_index per quel caso). A differenza del
# glitch Z->2, qui non c'e' ambiguita' da risolvere con un "suspect scan": un
# codice valido inizia sempre per lettera maiuscola o cifra (_CODE_RE), quindi
# un primo carattere che non e' ne' l'uno ne' l'altro non puo' mai far parte di
# un codice genuino, ed e' sempre sicuro rimuoverlo se il resto del token
# combacia con _CODE_RE.
_CAUSALE_CORRECTION_REASONS = {
    "font_digit_lettera": "glitch font Z->2, v. issue GH #4",
    "prefisso_spurio": "carattere spurio anteposto al codice, v. issue GH #5",
}


def _recover_causale_code(raw_code: str) -> tuple[str, str | None]:
    """Ritorna (codice, tipo_correzione). tipo_correzione e' None se il codice
    era gia' valido, altrimenti la chiave in _CAUSALE_CORRECTION_REASONS che
    descrive l'euristica di recupero applicata. Vedi nota sopra
    _SUSPECT_LEADING_2_RE sul perche' solo il caso 'digit seguito da lettera'
    lascia un residuo di ambiguita' (suspect scan) mentre lo strip del
    prefisso spurio no."""
    if _CODE_RE.match(raw_code):
        return raw_code, None
    if len(raw_code) > 1 and raw_code[0] == _CAUSALE_CORRUPT_DIGIT and raw_code[1].isalpha():
        candidate = _CAUSALE_CORRECT_LETTER + raw_code[1:]
        if _CODE_RE.match(candidate):
            return candidate, "font_digit_lettera"
    if len(raw_code) > 1 and not ("A" <= raw_code[0] <= "Z") and not raw_code[0].isdigit():
        candidate = raw_code[1:]
        if _CODE_RE.match(candidate):
            return candidate, "prefisso_spurio"
    return raw_code, None


def _leading_code_index(words: list[Word]) -> int | None:
    """Trova l'indice del token codice-causale, tollerando fino a
    _MAX_LEADING_MARKERS marcatori spuri iniziali. Il glitch di font che corrompe
    l'intestazione colonne (v. issue GH #3, 07.pdf/08.pdf/202201.pdf) rende anche
    il marker di riga in modo imprevedibile: non solo l'asterisco letterale, ma
    anche un apostrofo spurio o sequenze come 'I<'. Il codice vero resta pero'
    sempre entro le prime _MAX_LEADING_MARKERS+1 parole della riga."""
    for idx in range(min(len(words), _MAX_LEADING_MARKERS + 1)):
        text = words[idx].text
        if _CODE_RE.match(text) or _recover_causale_code(text)[1] is not None:
            return idx
    return None


def _parse_causale_row(row: Row) -> tuple[PayLineDTO, tuple[str, str, str] | None] | None:
    words = row.words
    idx = _leading_code_index(words)
    if idx is None:
        return None
    code_word = words[idx]
    codice, correction_kind = _recover_causale_code(code_word.text)
    causale_correction = (code_word.text, codice, correction_kind) if correction_kind else None
    idx += 1

    # La descrizione e' la sequenza di parole "non numeriche" dopo il codice: alcune
    # causali (es. "Contributo Previp C/Ditta") hanno etichette lunghe che sfondano
    # oltre il confine nominale della colonna IMPORTO BASE, quindi il limite non e'
    # una x fissa ma "fino al primo token che sembra un dato".
    data_start = len(words)
    for i in range(idx, len(words)):
        if _looks_like_data(words[i].text):
            data_start = i
            break
    desc_words = words[idx:data_start]
    data_words = words[data_start:]

    descrizione = " ".join(w.text for w in desc_words).strip()
    if not descrizione:
        return None

    buckets: dict[str, list[Word]] = {"importo_base": [], "riferimento": [], "importo": []}
    for w in data_words:
        buckets[_column_of(w.x0)].append(w)

    importo_base = _first_amount(buckets["importo_base"]) if buckets["importo_base"] else None

    quantita = None
    aliquota = None
    unita = None
    riferimento_words = [w for w in buckets["riferimento"] if w.text not in _PAREN_MARKERS]
    unit_words = [w for w in riferimento_words if w.text in UNIT_TOKENS]
    numeric_words = [w for w in riferimento_words if w.text not in UNIT_TOKENS]
    if unit_words:
        unita = unit_words[0].text
    if numeric_words:
        value = parse_amount(numeric_words[0].text)
        if unita == "%":
            aliquota = value
        else:
            quantita = value

    trattenuta, competenza = _split_amount_zone(buckets["importo"])

    line = PayLineDTO(
        codice=codice,
        descrizione=descrizione,
        categoria=_classify_causale(descrizione),
        is_recognized=True,
        importo_base=importo_base,
        quantita=quantita,
        unita=unita,
        aliquota=aliquota,
        trattenuta=trattenuta,
        competenza=competenza,
        raw_text=row.text,
        classification=DataClassification.OPZIONALE,
    )
    return line, causale_correction


def _fallback_causale_bounds(rows: list[Row]) -> tuple[int | None, int]:
    """Fallback quando la riga di intestazione 'TRATTENUTE COMPETENZE' e' corrotta
    oltre quanto normalize_label puo' tollerare (osservato su 07.pdf/08.pdf/202201.pdf,
    v. issue GH #3: non il solito glitch spazio->'s', ma glyph totalmente
    irriconoscibili). Le righe voce restano leggibili: l'ancora diventa la prima
    riga, dopo l'header, il cui codice causale e' riconoscibile (v.
    _leading_code_index), a prescindere dal testo dell'intestazione colonne."""
    start_idx = None
    end_idx = len(rows)
    for i, row in enumerate(rows):
        if row.top < _HEADER_MAX_TOP:
            continue
        if start_idx is None:
            if _leading_code_index(row.words) is not None:
                start_idx = i
            continue
        norm = normalize_label(row.text)
        if norm.startswith(_TFR_BOUNDARY_LABEL) or "totalecompetenze" in norm:
            end_idx = i
            break
    return start_idx, end_idx


def _extract_causale_rows(rows: list[Row]) -> tuple[list[PayLineDTO], list[str], list[tuple[str, str, str]]]:
    """Analizza le righe voce dinamiche, delimitate tra l'intestazione colonne e
    'Retribuzione utile T.F.R.' (o il primo TOTALE, se il TFR non e' presente).
    Il terzo elemento ritornato sono le correzioni automatiche codice_causale
    (originale, corretto, tipo_correzione) applicate da _recover_causale_code,
    da segnalare come anomalia esplicita in map_document (v.
    _CAUSALE_CORRECTION_REASONS)."""
    start_idx = None
    end_idx = len(rows)
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        if start_idx is None and "trattenute" in norm and "competenze" in norm:
            start_idx = i + 1
            continue
        if start_idx is not None and (norm.startswith(_TFR_BOUNDARY_LABEL) or "totalecompetenze" in norm):
            end_idx = i
            break
    if start_idx is None:
        start_idx, end_idx = _fallback_causale_bounds(rows)
        if start_idx is None:
            return [], [], []

    pay_lines: list[PayLineDTO] = []
    unmapped: list[str] = []
    corrections: list[tuple[str, str, str]] = []
    for row in rows[start_idx:end_idx]:
        parsed = _parse_causale_row(row)
        if parsed is not None:
            line, correction = parsed
            pay_lines.append(line)
            if correction is not None:
                corrections.append(correction)
        elif row.text.strip():
            stripped = row.text.strip()
            if _NOISE_ROW_RE.match(stripped):
                continue
            if normalize_label(stripped) in _BARE_SECTION_LABELS:
                # Titolo di sezione senza alcun dato accanto (v.
                # _BARE_SECTION_LABELS, issue GH #11): non e' una riga di
                # continuazione della voce precedente, va scartato come il
                # rumore sopra, non agganciato ne' segnalato come non mappato.
                continue
            # Zucchetti stampa a volte una riga di continuazione senza codice
            # causale proprio, sotto la voce a cui si riferisce (es. "Riferimento
            # anno 2020/2021" sotto un arretrato, o "MBO" sotto "Premio per
            # obiettivi", v. issue GH #7/#8): non e' una voce a se stante, quindi
            # non ha senso segnalarla come "non mappata" se puo' essere agganciata
            # alla voce appena riconosciuta prima di lei. Se invece non c'e' ancora
            # nessuna voce precedente in questa sezione, resta genuinamente
            # orfana e va segnalata come prima.
            if pay_lines:
                previous = pay_lines[-1]
                previous.note = f"{previous.note} | {row.text}" if previous.note else row.text
            else:
                unmapped.append(row.text)
    return pay_lines, unmapped, corrections


def _extract_tax(pay_lines: list[PayLineDTO], rows: list[Row]) -> TaxDTO:
    tax = TaxDTO()
    remaining: list[PayLineDTO] = []
    for line in pay_lines:
        field = _TAX_CODE_FIELDS.get(line.codice or "")
        if field:
            setattr(tax, field, line.competenza or line.importo_base or line.trattenuta)
        else:
            remaining.append(line)
    pay_lines[:] = remaining

    for row in rows:
        norm = normalize_label(row.text)
        # "in" e non "startswith": la riga e' sempre precisa dal codice causale
        # (es. "F09110 Addizionale regionale ..."), quindi l'etichetta non e' mai
        # all'inizio della riga.
        if normalize_label("Addizionale regionale") in norm:
            nums = [w.text for w in row.words if parse_amount(w.text) is not None]
            region_match = re.search(r"\d{4}\s+([A-Z]+)\s+Residuo", row.text)
            tax.addizionale_regionale_regione = region_match.group(1) if region_match else None
            if nums:
                tax.addizionale_regionale = parse_amount(nums[-1])
        elif normalize_label("Addizionale comunale") in norm:
            nums = [w.text for w in row.words if parse_amount(w.text) is not None]
            if nums:
                tax.addizionale_comunale = parse_amount(nums[-1])
        elif normalize_label("Acconto addiz. comunale") in norm:
            nums = [w.text for w in row.words if parse_amount(w.text) is not None]
            if nums:
                tax.acconto_addizionale_comunale = parse_amount(nums[-1])
    return tax


_TFR_COLUMN_MARKERS = [
    ("rivalutaz", "rivalutazione"),
    ("imp.rival", "imponibile_rivalutazione"),
    ("quota", "quota_anno"),
    ("anticipi", "anticipi"),
]


def _extract_tfr(rows: list[Row]) -> TfrDTO:
    tfr = TfrDTO()
    simple_field_map = {
        normalize_label("Retribuzione utile T.F.R."): "retribuzione_utile_tfr",
        normalize_label("Quota T.F.R. a Fondi"): "quota_tfr_fondi",
    }
    for row in rows:
        norm = normalize_label(row.text)
        for label_norm, field in simple_field_map.items():
            if norm.startswith(label_norm):
                amount = _first_amount(row.words)
                if amount is not None:
                    setattr(tfr, field, amount)
                break

    # Sotto-tabella "T.F.R. F.do 31/12 | Rivalutaz. | Imp.rival. | Quota anno | TFR a
    # fondi | Anticipi": intestazioni di colonna su una riga, valori senza etichetta
    # sulla riga successiva, allineati alla colonna per x0 (non tutte le colonne sono
    # sempre popolate, es. "Anticipi" resta vuoto se non ce ne sono stati).
    for i, row in enumerate(rows):
        lowered = row.text.lower()
        if "rivalutaz" in lowered and "imp.rival" in lowered and i + 1 < len(rows):
            marker_positions = [
                (w.x0, field)
                for w in row.words
                for marker, field in _TFR_COLUMN_MARKERS
                if marker in w.text.lower()
            ]
            if not marker_positions:
                break
            for field, amount in match_column_values(
                marker_positions, rows[i + 1].words, _TFR_COLUMN_MATCH_TOLERANCE
            ).items():
                setattr(tfr, field, amount)
            break
    return tfr


_LEFT_BLOCK_MAX_X = 400.0
_LEAVE_ROW_WINDOW = 6


def _extract_leave_balances(rows: list[Row]) -> list[LeaveBalanceDTO]:
    """Riga colonne 'Maturato Goduto Residuo Residuo AP' seguita dalle righe
    'Ferie'/'Perm.Ex-Fs' con i valori corrispondenti. Le righe di questo blocco
    (colonna sinistra/centrale) condividono la coordinata verticale con righe del
    blocco TOTALE/ARROTONDAMENTO (colonna destra, x0 >= 400): vanno escluse quelle,
    non solo per top ma anche per x, altrimenti si mescolano valori di blocchi diversi."""
    balances: list[LeaveBalanceDTO] = []
    header_idx = None
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        if "maturato" in norm and "goduto" in norm and normalize_label("residuo") in norm:
            header_idx = i
            break
    if header_idx is None:
        return balances

    for row in rows[header_idx + 1 : header_idx + 1 + _LEAVE_ROW_WINDOW]:
        left_words = [w for w in row.words if w.x0 < _LEFT_BLOCK_MAX_X]
        if not left_words or left_words[0].x0 >= 100:
            continue
        data_start = len(left_words)
        for j, w in enumerate(left_words):
            if _looks_like_data(w.text):
                data_start = j
                break
        tipo = " ".join(w.text for w in left_words[:data_start]).strip()
        if not tipo:
            continue
        amounts = [parse_amount(w.text) for w in left_words[data_start:] if w.text not in UNIT_TOKENS]
        amounts = [a for a in amounts if a is not None]
        if not amounts:
            continue
        balances.append(
            LeaveBalanceDTO(
                tipo=tipo,
                maturato=amounts[0] if len(amounts) > 0 else None,
                goduto=amounts[1] if len(amounts) > 1 else None,
                residuo=amounts[2] if len(amounts) > 2 else None,
                residuo_ap=amounts[3] if len(amounts) > 3 else None,
            )
        )
    return balances


# Glitch di font O->0 confermato su 07.pdf/08.pdf (issue GH #4): il CIN (5o
# carattere di un IBAN italiano) e' sempre una lettera, quindi una cifra in
# quella posizione e' un segnale di corruzione in un punto strutturalmente
# noto. A differenza dei codici causale, qui esiste un verificatore
# indipendente (il checksum standard IBAN ISO 7064 mod 97-10): proviamo le
# sostituzioni cifra->lettera visivamente plausibili in quella sola posizione
# e accettiamo solo quella che supera il checksum, cosi' da non indovinare un
# dato bancario senza una conferma matematica.
_IBAN_CONFUSABLE_CIN = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}


def _recover_iban(raw: str) -> tuple[str, bool]:
    """Ritorna (iban, corretto_automaticamente). Vedi nota sopra _IBAN_CONFUSABLE_CIN."""
    if len(raw) != 27 or not raw.startswith("IT") or not raw[4].isdigit():
        return raw, False
    letter = _IBAN_CONFUSABLE_CIN.get(raw[4])
    if letter is None:
        return raw, False
    candidate = raw[:4] + letter + raw[5:]
    if _iban_mod97_valid(candidate):
        return candidate, True
    return raw, False


_PROGRESSIVI_LABEL_NORM = normalize_label("PROGRESSIVI")


def _extract_progressivi(rows: list[Row]) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Sotto-tabella 'PROGRESSIVI Imp. INPS Imp. INAIL Imp. IRPEF IRPEF pagata':
    intestazioni di colonna su una riga, valori senza etichetta sulla riga
    successiva, allineati per x0 (stesso pattern gia' usato per la sotto-tabella
    T.F.R., v. _extract_tfr). "IRPEF" compare due volte nell'intestazione (colonna
    "Imp. IRPEF" e colonna "IRPEF pagata"): solo la prima occorrenza ha un campo
    corrispondente in PayrollTotalsDTO, la seconda va ignorata esplicitamente
    (altrimenti il suo valore, piu' a destra, sovrascriverebbe quello corretto)."""
    for i, row in enumerate(rows):
        if not normalize_label(row.text).startswith(_PROGRESSIVI_LABEL_NORM):
            continue
        marker_positions: list[tuple[float, str]] = []
        seen_irpef = False
        for w in row.words:
            if w.text == "INPS":
                marker_positions.append((w.x0, "imponibile_inps"))
            elif w.text == "INAIL":
                marker_positions.append((w.x0, "imponibile_inail"))
            elif w.text == "IRPEF" and not seen_irpef:
                marker_positions.append((w.x0, "imponibile_irpef"))
                seen_irpef = True
        if not marker_positions or i + 1 >= len(rows):
            # "PROGRESSIVI" da solo, senza le colonne Imp. INPS/INAIL/IRPEF
            # accanto, e' un'etichetta di sezione vuota (osservato in cedolini
            # a piu' pagine dove i dati sono su un'altra pagina, v. issue GH
            # #9/#11): non e' la riga giusta, ma potrebbe essercene un'altra
            # piu' avanti (su un'altra pagina) con i dati veri - continua la
            # ricerca invece di arrenderti al primo match testuale.
            continue
        values = match_column_values(marker_positions, rows[i + 1].words, _TFR_COLUMN_MATCH_TOLERANCE)
        return values.get("imponibile_inps"), values.get("imponibile_inail"), values.get("imponibile_irpef")
    return None, None, None


def _extract_totals(rows: list[Row]) -> PayrollTotalsDTO:
    totals = PayrollTotalsDTO()
    netto_label_norm = normalize_label("NETTO DEL MESE")
    totale_competenze_norm = normalize_label("TOTALE COMPETENZE")
    totale_trattenute_norm = normalize_label("TOTALE TRATTENUTE")
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        # "in" e non "startswith": alcune etichette (es. "TOTALE COMPETENZE") sono
        # precedute sulla stessa riga da un titolo di sezione ("RATEI ...").
        if totale_competenze_norm in norm:
            totals.totale_competenze = _amount_after_label(row.words, totale_competenze_norm)
        elif totale_trattenute_norm in norm:
            totals.totale_trattenute = _amount_after_label(row.words, totale_trattenute_norm)
        elif norm == netto_label_norm:
            # Il valore "NETTO DEL MESE" e' reso in un riquadro grafico separato,
            # sulla riga successiva (~10pt piu' in basso), non su questa stessa riga.
            for next_row in rows[i + 1 : i + 3]:
                amount = _first_amount(next_row.words)
                if amount is not None:
                    totals.netto_mese = amount
                    break
        elif "iban" in norm:
            iban_match = re.search(r"IBAN\s+([A-Z]{2}\s*[A-Z0-9\s]+)", row.text)
            if iban_match:
                totals.iban = re.sub(r"\s+", "", iban_match.group(1))

    # Imp. INPS/INAIL/IRPEF non sono su questa riga ma sulla sotto-tabella
    # "PROGRESSIVI" (etichette di colonna su una riga, valori sulla successiva,
    # v. issue GH #13): il vecchio codice cercava un importo sulla stessa riga
    # dell'etichetta "Imp. INPS"/"Imp. INAIL", che qui non c'e' mai (per INPS)
    # o appartiene a un'annotazione diversa e semanticamente non equivalente
    # (per INAIL, la riga "Imp. INAIL ... Voce Tariffa ..." e' la base
    # imponibile della singola voce, non il progressivo).
    totals.imponibile_inps, totals.imponibile_inail, totals.imponibile_irpef = _extract_progressivi(rows)
    return totals


def map_document(doc: RawExtractedDocument) -> PayrollDocumentDTO:
    page = doc.first_page
    rows = page.rows
    # Alcuni cedolini (conguaglio annuale allegato nello stesso PDF, v. issue GH
    # #9) stampano i box "TOTALE COMPETENZE/TRATTENUTE", "NETTO DEL MESE", IBAN
    # e la sotto-tabella T.F.R./ferie solo sull'ULTIMA pagina, lasciando quelle
    # etichette vuote (o assenti) sulla prima. Le funzioni di estrazione "a
    # scansione" (totali, tax addizionali, tfr, ferie) cercano un'etichetta nota
    # su tutte le righe passate e sovrascrivono il valore trovato ad ogni match:
    # concatenare le righe di TUTTE le pagine nell'ordine del documento le rende
    # multi-pagina "gratis", perche' l'ultimo match (pagina successiva, quella
    # col dato reale) sovrascrive sempre l'eventuale match vuoto/spurio di una
    # pagina precedente. Per i documenti a pagina singola (la stragrande
    # maggioranza) all_rows coincide esattamente con rows, quindi il
    # comportamento esistente non cambia.
    # L'header anagrafico e le righe voce (_parse_header/_extract_causale_rows)
    # restano deliberatamente ancorati alla sola prima pagina: la delimitazione
    # dei confini della tabella voci (v. _fallback_causale_bounds, issue GH #11)
    # non e' pensata per un flusso multi-pagina e concatenare rischierebbe di
    # introdurre nuovi falsi positivi/negativi non necessari a risolvere #9.
    all_rows = [r for p in doc.pages for r in p.rows]

    company, employee, hire_date_str, tipo_costo_text = _parse_header(rows)

    # Un glitch di font puo' corrompere una lettera del codice fiscale in
    # un'altra lettera plausibile (osservato su 202201.pdf: 'T' reso come 'I',
    # v. issue GH #10) senza che il formato (_EMPLOYEE_ROW_RE) se ne accorga.
    # A differenza dell'IBAN, qui non tentiamo una correzione automatica: non
    # c'e' un modo strutturale di sapere quale carattere sia stato corrotto (il
    # CIN dell'IBAN ha una posizione nota che deve essere una lettera; qui ogni
    # posizione del blocco lettere e' ugualmente plausibile) e un identificativo
    # fiscale/legale sbagliato per un falso positivo di correzione avrebbe
    # conseguenze piu' gravi di un IBAN da verificare a mano. Trattiamo quindi
    # il documento come se il codice fiscale non fosse stato riconosciuto (non
    # crea ne' collega alcun Employee, v. repository.save_document), cosi' non
    # si frammenta silenziosamente l'identita' della stessa persona su due
    # record employee distinti.
    codice_fiscale_originale = employee.codice_fiscale
    codice_fiscale_non_valido = bool(employee.codice_fiscale) and not _codice_fiscale_checksum_valido(
        employee.codice_fiscale
    )
    if codice_fiscale_non_valido:
        employee.codice_fiscale = ""

    pay_lines, unmapped_rows, causale_corrections = _extract_causale_rows(rows)
    tax = _extract_tax(pay_lines, all_rows)
    tfr = _extract_tfr(all_rows)
    leave_balances = _extract_leave_balances(all_rows)
    totals = _extract_totals(all_rows)

    iban_correction: tuple[str, str] | None = None
    if totals.iban:
        corrected_iban, iban_corretto = _recover_iban(totals.iban)
        if iban_corretto:
            iban_correction = (totals.iban, corrected_iban)
            totals.iban = corrected_iban

    period_type = _detect_period_type(tipo_costo_text, pay_lines)
    month_year = parse_italian_month_year(tipo_costo_text or "")
    if month_year is None:
        period = PeriodDTO(
            mese=0,
            anno=0,
            tipo=period_type,
            label_originale=tipo_costo_text or "",
            classification=DataClassification.NON_RICONOSCIUTO,
        )
    else:
        mese, anno = month_year
        period = PeriodDTO(mese=mese, anno=anno, tipo=period_type, label_originale=tipo_costo_text or "")

    # parse_date_ddmmyyyy (non strptime) perche' il regex di riga valida solo il
    # formato sintattico, non la validita' calendariale: un refuso nel PDF o una
    # cifra letta male dall'OCR (es. "31-11-2021") non deve far perdere l'intero
    # documento con un'eccezione non gestita.
    hire_date = parse_date_ddmmyyyy(hire_date_str) if hire_date_str else None
    hire_date_invalid = bool(hire_date_str) and hire_date is None

    dto = PayrollDocumentDTO(
        company=company,
        employee=employee,
        period=period,
        pay_lines=pay_lines,
        tax=tax,
        tfr=tfr,
        leave_balances=leave_balances,
        totals=totals,
        unrecognized_row_texts=unmapped_rows,
        template_name=TEMPLATE_NAME,
        hire_date=hire_date,
    )

    if codice_fiscale_non_valido:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="codice_fiscale_non_valido",
                severita=AnomalySeverity.ERROR,
                messaggio=(
                    f"Codice fiscale {codice_fiscale_originale!r} non supera il controllo del "
                    "check-digit ufficiale (probabile glitch font su una lettera, v. issue GH #10) "
                    "- trattato come non riconosciuto per non creare un employee duplicato, "
                    "verificare manualmente"
                ),
                campo="employee.codice_fiscale",
            )
        )
    elif not employee.codice_fiscale:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="header_incompleto",
                severita=AnomalySeverity.ERROR,
                messaggio="Codice fiscale dipendente non riconosciuto",
                campo="employee.codice_fiscale",
            )
        )
    if not company.ragione_sociale:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="header_incompleto",
                severita=AnomalySeverity.ERROR,
                messaggio="Ragione sociale azienda non riconosciuta",
                campo="company.ragione_sociale",
            )
        )
    if period.mese == 0:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="periodo_non_riconosciuto",
                severita=AnomalySeverity.WARNING,
                messaggio=f"Periodo non riconosciuto dal testo: {tipo_costo_text!r}",
                campo="period",
            )
        )
    if hire_date_invalid:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="data_non_valida",
                severita=AnomalySeverity.WARNING,
                messaggio=f"Data di assunzione con formato riconosciuto ma non valida: {hire_date_str!r}",
                campo="hire_date",
            )
        )
    if unmapped_rows:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="righe_non_mappate",
                severita=AnomalySeverity.INFO,
                messaggio=f"{len(unmapped_rows)} righe nella sezione voci non sono state mappate",
                campo="pay_lines",
            )
        )

    for originale, corretto, correction_kind in causale_corrections:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="codice_causale_corretto_automaticamente",
                severita=AnomalySeverity.WARNING,
                messaggio=(
                    f"Codice causale {originale!r} corretto in {corretto!r} "
                    f"({_CAUSALE_CORRECTION_REASONS[correction_kind]}) - verificare manualmente"
                ),
                campo="pay_lines",
            )
        )

    if any(kind == "font_digit_lettera" for _, _, kind in causale_corrections):
        # La corruzione Z->2 e' gia' confermata su questo documento (v. sopra): un
        # codice puramente numerico che inizia per '2' e' quindi sospetto, ma senza
        # un checksum non possiamo correggerlo (v. nota su _SUSPECT_LEADING_2_RE).
        for line in pay_lines:
            if line.codice and _SUSPECT_LEADING_2_RE.match(line.codice):
                dto.anomalies.append(
                    AnomalyDTO(
                        tipo="codice_causale_sospetto",
                        severita=AnomalySeverity.WARNING,
                        messaggio=(
                            f"Codice causale {line.codice!r} e' puramente numerico e inizia con "
                            "'2': nello stesso documento e' confermata la corruzione del font "
                            "Z->2 su almeno un altro codice (v. issue GH #4). Verificare a mano "
                            "se anche questo era 'Z' + cifre."
                        ),
                        campo="pay_lines",
                    )
                )

    if iban_correction:
        originale_iban, corretto_iban = iban_correction
        dto.anomalies.append(
            AnomalyDTO(
                tipo="iban_corretto_automaticamente",
                severita=AnomalySeverity.WARNING,
                messaggio=(
                    f"IBAN {originale_iban!r} corretto in {corretto_iban!r} (CIN recuperato da "
                    "glitch font, verificato via checksum IBAN standard, v. issue GH #4) - "
                    "verificare manualmente"
                ),
                campo="totals.iban",
            )
        )

    # Netto e IBAN sono il dato con cui l'utente riconcilia gli accrediti reali
    # in banca: se restano assenti dopo l'estrazione (v. issue GH #9) il
    # documento non puo' essere considerato affidabile senza revisione umana,
    # a differenza delle correzioni sopra (auto-applicate con conferma
    # checksum/pattern). ERROR, non WARNING: forza NEEDS_REVIEW invece di
    # PROCESSED_WITH_ANOMALIES, cosi' il gap resta visibile a `check-years`
    # (che oggi guarda solo la tabella anomaly) invece di passare per un
    # documento pulito.
    missing_totals = [
        campo for campo, valore in (("netto_mese", totals.netto_mese), ("iban", totals.iban)) if valore is None
    ]
    if missing_totals:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="totali_mancanti",
                severita=AnomalySeverity.ERROR,
                messaggio=f"Campi totali non estratti da nessuna pagina del documento: {', '.join(missing_totals)}",
                campo="totals",
            )
        )

    return dto


SPEC = TemplateSpec(name=TEMPLATE_NAME, parser_version=PARSER_VERSION, detect=is_zucchetti_document, map=map_document)
