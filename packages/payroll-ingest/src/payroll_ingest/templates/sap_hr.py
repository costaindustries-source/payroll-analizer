"""Template per i cedolini "SAP HR" (produttore iText, datore ACCENTURE dal
2019-02 al 2020-13, 25 file). Nessuno di questi file e' mai stato prodotto dal
Win2PDF a avanzamento zero (v. docs/PIANO_TECNICO_NEW_TEMPLATES.md §3): la
frazione di caratteri a x0 coincidente e' 0.0 su tutti i 25 campioni verificati,
quindi qui non serve alcuna delle protezioni "testo compattato" usate in
copernico.py per i file ricostruiti.

Strategia ibrida (v. piano §6): righe clusterizzate per il corpo voci (stile
copernico.py/zucchetti.py), ma lookup per coordinate (non per riga) per i box
del footer (totali, TFR, detrazioni, ferie): le etichette di questi box e i
rispettivi valori finiscono spesso su Row diverse, a volte non adiacenti (v.
NETTO, §2.2 del piano)."""

import re
from datetime import date
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
from payroll_ingest.normalize import normalize_label, parse_amount
from payroll_ingest.templates._common import (
    PAREN_MARKERS,
    codice_fiscale_checksum_valido,
    first_amount,
    iban_mod97_valid,
    looks_like_data,
    match_column_values,
)
from payroll_ingest.templates._spec import TemplateSpec

TEMPLATE_NAME = "sap_hr"
PARSER_VERSION = "1.0.0"

# --- Detection --------------------------------------------------------------

_HEADER_MAX_TOP = 230.0
_VOCI_RETRIBUTIVE_NORM = normalize_label("VOCI RETRIBUTIVE")


def is_sap_hr_document(doc: RawExtractedDocument) -> bool:
    page = doc.first_page
    has_voci_header = any(_VOCI_RETRIBUTIVE_NORM in normalize_label(row.text) for row in page.rows)
    # Mai la ragione sociale come marker: cambia nel 2020 (v. piano §2.2).
    # Confronto diretto (non normalize_label): "SAP" non ha alcuna 's' da
    # tollerare per glitch di font, e normalize_label la rimuoverebbe
    # comunque (e' il fix per lo spazio->'s' di Zucchetti, non applicabile
    # qui), rendendo un confronto con "sap" sempre falso.
    has_sap_nr = any(
        len(row.words) >= 2 and row.words[0].text.upper() == "SAP"
        for row in page.rows
        if row.top < _HEADER_MAX_TOP
    )
    return has_voci_header and has_sap_nr


# --- Header anagrafico --------------------------------------------------------

_LIBRO_UNICO_NORM = normalize_label("LIBRO UNICO DEL LAVORO")
_RAGIONE_SOCIALE_WORD_RE = re.compile(r"^[A-Z&.]+$")
_CF_PERSONA_RE = re.compile(r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$")
_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def _parse_ragione_sociale(rows: list[Row]) -> str:
    """La ragione sociale non e' un marker stabile (cambia nome nel 2020, v.
    piano §2.2): e' ancorata strutturalmente subito dopo la riga boilerplate
    "LIBRO UNICO DEL LAVORO", presa come le parole maiuscole (+ '&'/'.') di
    inizio riga, fino al primo token che non e' piu' testo puro (indirizzo,
    codici)."""
    anchor_idx = None
    for i, row in enumerate(rows):
        if _LIBRO_UNICO_NORM in normalize_label(row.text):
            anchor_idx = i
            break
    if anchor_idx is None or anchor_idx + 1 >= len(rows):
        return ""
    name_words = []
    for w in rows[anchor_idx + 1].words:
        if _RAGIONE_SOCIALE_WORD_RE.match(w.text):
            name_words.append(w.text)
        else:
            break
    return " ".join(name_words)


def _parse_matricola_codice(rows: list[Row]) -> tuple[str | None, str | None]:
    matricola: str | None = None
    codice_azienda: str | None = None
    for row in rows:
        words = row.words
        if len(words) == 2 and words[0].text.rstrip(":").upper() == "CODICE" and words[1].text.isdigit():
            codice_azienda = words[1].text
        if len(words) >= 2 and words[0].text.upper() == "SAP" and words[-1].text.isdigit():
            matricola = words[-1].text
    return matricola, codice_azienda


def _parse_codice_fiscale(rows: list[Row]) -> str:
    """Il CF azienda (11 cifre) e il CF persona (16 alfanumerico) sono su righe
    diverse: il regex a 16 caratteri non matcha mai l'11 cifre, quindi non
    serve escluderlo esplicitamente (v. piano §2.2)."""
    for row in rows:
        for w in row.words:
            if _CF_PERSONA_RE.match(w.text):
                return w.text
    return ""


def _parse_hire_date_str(rows: list[Row]) -> str | None:
    for i, row in enumerate(rows):
        if "assunzione" in row.text.lower() and i + 1 < len(rows):
            dates = [w.text for w in rows[i + 1].words if _DATE_RE.match(w.text)]
            if dates:
                # "Data Ass. Conv." precede "Data Assunzione" sulla stessa riga
                # valori (colonna piu' a sinistra vs piu' a destra): la seconda
                # (piu' a destra) e' la data di assunzione vera e propria.
                return dates[-1]
    return None


def _parse_header(rows: list[Row]) -> tuple[CompanyDTO, EmployeeDTO, str | None]:
    header_rows = [r for r in rows if r.top < _HEADER_MAX_TOP]
    ragione_sociale = _parse_ragione_sociale(header_rows)
    matricola, codice_azienda = _parse_matricola_codice(header_rows)
    codice_fiscale = _parse_codice_fiscale(header_rows)
    hire_date_str = _parse_hire_date_str(header_rows)

    company = CompanyDTO(ragione_sociale=ragione_sociale, codice_azienda=codice_azienda)
    employee = EmployeeDTO(cognome_nome="", codice_fiscale=codice_fiscale, matricola=matricola)
    return company, employee, hire_date_str


def _parse_date_slash(text: str) -> date | None:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


# --- Periodo ------------------------------------------------------------------

_MESI_IT = {
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
_PERIOD_MESE_RE = re.compile(
    r"(Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|Luglio|Agosto|Settembre|Ottobre|Novembre|Dicembre)\s+(\d{4})",
    re.IGNORECASE,
)


def _parse_period(rows: list[Row]) -> tuple[PeriodType, int, int, str]:
    for row in rows:
        m = _PERIOD_MESE_RE.search(row.text)
        if m:
            mese = _MESI_IT[m.group(1).lower()]
            anno = int(m.group(2))
            # Per la tredicesima il mese testuale e' gia' "Dicembre" (v. piano
            # §2.2/§6, campione 202013.pdf): non serve forzare mese=12 a parte,
            # basta rilevare l'etichetta "Tredicesima" per il tipo periodo.
            tipo = PeriodType.MENSILITA_AGGIUNTIVA if "tredicesima" in row.text.lower() else PeriodType.ORDINARIO
            return tipo, mese, anno, row.text.strip()
    return PeriodType.ORDINARIO, 0, 0, ""


# --- Corpo voci -----------------------------------------------------------

_CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")
_SEZ2_START_NORM = normalize_label("TRATTENUTE PREVIDENZIALI")
_ADDIZIONALI_START_NORM = normalize_label("ADDIZIONALI")

# Soglie x0 calibrate su docs/new-templates/2020/202001.pdf, v. piano §2.2.
# TRATTENUTE_MIN/COMPETENZE_MIN sono condivise da entrambe le sezioni voci
# (stessa posizione fisica delle due colonne su tutta la pagina).
TRATTENUTE_MIN = 455.0
COMPETENZE_MIN = 520.0
ORE_GIORNI_MIN = 230.0
IMPORTO_UNITARIO_MIN = 280.0
IMPORTI_FIGURATI_MIN = 365.0
IMPONIBILI_MIN = 300.0
ALIQUOTE_MIN = 385.0

# Ordine di controllo dal piu' alto x0 al piu' basso (v. _column_of): ogni voce
# "VOCI RETRIBUTIVE" ha le colonne Ore/Giorni, Importo Unitario, Importi
# Figurati (valori esclusivamente figurativi, v. piano); "TRATTENUTE
# PREVIDENZIALI" (che qui include anche le righe CTB.DED. intermedie, v.
# piano §2.2) ha Imponibili/Aliquote al posto delle prime due.
_SECTION1_ZONES: list[tuple[float, str]] = [
    (COMPETENZE_MIN, "competenza"),
    (TRATTENUTE_MIN, "trattenuta"),
    (IMPORTI_FIGURATI_MIN, "importi_figurati"),
    (IMPORTO_UNITARIO_MIN, "importo_base"),
    (ORE_GIORNI_MIN, "ore_giorni"),
]
_SECTION2_ZONES: list[tuple[float, str]] = [
    (COMPETENZE_MIN, "competenza"),
    (TRATTENUTE_MIN, "trattenuta"),
    (ALIQUOTE_MIN, "aliquota"),
    (IMPONIBILI_MIN, "importo_base"),
]


def _column_of(x0: float, zones: list[tuple[float, str]]) -> str | None:
    for threshold, name in zones:
        if x0 >= threshold:
            return name
    return None


def _parse_pay_line_row(row: Row, zones: list[tuple[float, str]]) -> PayLineDTO | None:
    words = row.words
    if not words or not _CODE_RE.match(words[0].text):
        return None
    codice = words[0].text

    data_start = len(words)
    for i in range(1, len(words)):
        if looks_like_data(words[i].text):
            data_start = i
            break
    desc_words = words[1:data_start]
    data_words = words[data_start:]

    descrizione = " ".join(w.text for w in desc_words).strip()
    if not descrizione:
        return None

    values: dict[str, Decimal] = {}
    figurativo = False
    for w in data_words:
        if w.text in PAREN_MARKERS:
            continue
        amount = parse_amount(w.text)
        if amount is None:
            continue
        field = _column_of(w.x0, zones)
        if field == "importi_figurati":
            figurativo = True
            continue
        if field is not None:
            values[field] = amount

    return PayLineDTO(
        codice=codice,
        descrizione=descrizione,
        categoria=PayLineCategory.ALTRO,
        is_recognized=True,
        importo_base=values.get("importo_base"),
        quantita=values.get("ore_giorni"),
        aliquota=values.get("aliquota"),
        trattenuta=values.get("trattenuta"),
        competenza=values.get("competenza"),
        raw_text=row.text,
        note="valore esclusivamente figurativo (non concorre al netto)" if figurativo else None,
        classification=DataClassification.OPZIONALE,
    )


def _extract_pay_lines_from_page(rows: list[Row]) -> tuple[list[PayLineDTO], list[str]]:
    pay_lines: list[PayLineDTO] = []
    unmapped: list[str] = []
    section: int | None = None
    for row in rows:
        norm = normalize_label(row.text)
        if section is None:
            if _VOCI_RETRIBUTIVE_NORM in norm:
                section = 1
            continue
        if _SEZ2_START_NORM in norm:
            section = 2
            continue
        if _ADDIZIONALI_START_NORM in norm:
            break
        zones = _SECTION1_ZONES if section == 1 else _SECTION2_ZONES
        parsed = _parse_pay_line_row(row, zones)
        if parsed is not None:
            pay_lines.append(parsed)
        elif row.text.strip():
            unmapped.append(row.text)
    return pay_lines, unmapped


# --- Tax ------------------------------------------------------------------

_FOOTER_BOX_START_NORM = normalize_label("Descrizione Imponibile Fiscale")
FOOTER_MATCH_TOLERANCE = 40.0


def _extract_imponibile_irpef(rows: list[Row]) -> Decimal | None:
    for row in rows:
        lowered = row.text.lower()
        if "emolumenti" in lowered and "correnti" in lowered:
            return first_amount(row.words)
    return None


def _build_detrazioni_markers(row: Row) -> list[tuple[float, str]]:
    """"Imposta Lorda"/"Imposta Netta"/"Detr. Lav. Dip." sono etichette a piu'
    parole nella stessa riga di altre etichette simili ma non mappate (Detr.
    Coniuge/Figli/Altri Fam., Totale Detrazioni, v. piano §2.2): serve
    guardare la parola successiva (Lorda/Netta) o precedente (Detr.) per
    disambiguare, non basta un singolo token."""
    markers: list[tuple[float, str]] = []
    words = row.words
    for i, w in enumerate(words):
        low = w.text.lower()
        if low == "imposta" and i + 1 < len(words):
            nxt = words[i + 1].text.lower()
            if nxt.startswith("lord"):
                markers.append((w.x0, "irpef_lorda"))
            elif nxt.startswith("nett"):
                markers.append((w.x0, "ritenute_irpef"))
        elif low.startswith("lav") and i > 0 and words[i - 1].text.lower().startswith("detr"):
            markers.append((words[i - 1].x0, "detrazioni_lav_dip"))
    return markers


def _extract_tax(rows: list[Row]) -> TaxDTO:
    tax = TaxDTO()
    tax.imponibile_irpef = _extract_imponibile_irpef(rows)

    for i, row in enumerate(rows):
        markers = _build_detrazioni_markers(row)
        if markers and i + 1 < len(rows):
            values = match_column_values(markers, rows[i + 1].words, FOOTER_MATCH_TOLERANCE)
            if "irpef_lorda" in values:
                tax.irpef_lorda = values["irpef_lorda"]
            if "detrazioni_lav_dip" in values:
                tax.detrazioni_lav_dip = values["detrazioni_lav_dip"]
            if "ritenute_irpef" in values:
                tax.ritenute_irpef = values["ritenute_irpef"]
            break

    in_addizionali = False
    pending: str | None = None
    for row in rows:
        norm = normalize_label(row.text)
        if not in_addizionali:
            if _ADDIZIONALI_START_NORM in norm:
                in_addizionali = True
            continue
        if _FOOTER_BOX_START_NORM in norm:
            break
        words = row.words
        if not words:
            continue
        if _CODE_RE.match(words[0].text) and len(words) > 1:
            descr_norm = normalize_label(" ".join(w.text for w in words[1:]))
            amount = first_amount(words[1:])
            if "addizionaleregionale" in descr_norm:
                tax.addizionale_regionale = amount
                pending = "regionale"
            elif "addizionalecomunale" in descr_norm:
                tax.addizionale_comunale = amount
                pending = "comunale"
            else:
                pending = None
        elif pending == "regionale" and len(words) == 1:
            tax.addizionale_regionale_regione = words[0].text
            pending = None
        elif pending == "comunale" and len(words) == 1:
            # Il comune di continuazione non ha un campo dedicato nel DTO
            # (solo addizionale_regionale_regione esiste), v. piano §6.
            pending = None
    return tax


# --- TFR --------------------------------------------------------------------

_TFR_MARKERS = [("accant", "quota_anno"), ("tesoreria", "quota_tfr_fondi"), ("anticipazioni", "anticipi")]


def _extract_tfr(rows: list[Row]) -> TfrDTO:
    tfr = TfrDTO()
    for i, row in enumerate(rows):
        lowered = row.text.lower()
        if "accant" in lowered and "anticipazioni" in lowered and i + 1 < len(rows):
            marker_positions = [
                (w.x0, field) for w in row.words for marker, field in _TFR_MARKERS if marker in w.text.lower()
            ]
            if marker_positions:
                values = match_column_values(marker_positions, rows[i + 1].words, FOOTER_MATCH_TOLERANCE)
                for field, amount in values.items():
                    setattr(tfr, field, amount)
            break
    for i, row in enumerate(rows):
        lowered = row.text.lower()
        if "retr" in lowered and "utile" in lowered and "tfr" in lowered and i + 1 < len(rows):
            amount = first_amount(rows[i + 1].words)
            if amount is not None:
                tfr.retribuzione_utile_tfr = amount
            break
    return tfr


# --- Ferie ------------------------------------------------------------------

_LEAVE_ROW_LABELS = {"FERIE": "ferie", "R.O.L.": "rol_ex_festivita", "B.ORE": "banca_ore_riposi"}


def _build_leave_markers(header_row: Row) -> list[tuple[float, str]]:
    markers: list[tuple[float, str]] = []
    words = header_row.words
    i = 0
    while i < len(words):
        low = words[i].text.lower()
        if low == "maturate":
            markers.append((words[i].x0, "maturato"))
        elif low == "godute":
            markers.append((words[i].x0, "goduto"))
        elif low == "residue" and i + 1 < len(words):
            suffix = words[i + 1].text.upper()
            if suffix == "AP2":
                markers.append((words[i].x0, "residuo_ap2"))
            elif suffix == "AP":
                markers.append((words[i].x0, "residuo_ap"))
        elif low == "saldo":
            markers.append((words[i].x0, "residuo"))
        i += 1
    return markers


_LEAVE_HEADER_MATURATE_NORM = normalize_label("Maturate")
_LEAVE_HEADER_GODUTE_NORM = normalize_label("Godute")
_LEAVE_HEADER_RESIDUE_NORM = normalize_label("Residue")
_LEAVE_HEADER_SALDO_NORM = normalize_label("Saldo")


def _extract_leave_balances(rows: list[Row]) -> list[LeaveBalanceDTO]:
    header_idx = None
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        if (
            _LEAVE_HEADER_MATURATE_NORM in norm
            and _LEAVE_HEADER_GODUTE_NORM in norm
            and _LEAVE_HEADER_RESIDUE_NORM in norm
            and _LEAVE_HEADER_SALDO_NORM in norm
        ):
            header_idx = i
            break
    if header_idx is None:
        return []

    marker_positions = _build_leave_markers(rows[header_idx])
    if not marker_positions:
        return []

    balances: list[LeaveBalanceDTO] = []
    for row in rows[header_idx + 1 : header_idx + 6]:
        if not row.words:
            continue
        tipo = _LEAVE_ROW_LABELS.get(row.words[0].text.upper())
        if tipo is None:
            continue
        values = match_column_values(marker_positions, row.words[1:], FOOTER_MATCH_TOLERANCE)
        if not values:
            continue
        balances.append(
            LeaveBalanceDTO(
                tipo=tipo,
                maturato=values.get("maturato"),
                goduto=values.get("goduto"),
                residuo=values.get("residuo"),
                residuo_ap=values.get("residuo_ap"),
            )
        )
        residuo_ap2 = values.get("residuo_ap2")
        if residuo_ap2 is not None and residuo_ap2 != 0:
            balances.append(LeaveBalanceDTO(tipo=f"{tipo}_ap2", residuo=residuo_ap2))
    return balances


# --- Riepilogo annuale (solo tipo=mensilita_aggiuntiva) --------------------

# Marker per individuare le due righe di riepilogo annuale (issue #31): dati
# fiscali/contributivi cumulati dell'anno, presenti solo sui 2 cedolini di
# tredicesima del corpus (201913.pdf, 202013.pdf), su un box a parte - riga
# di etichette seguita immediatamente dalla riga di valori.
_ANNUAL_TAX_ROW_NORM = normalize_label("Imponibile Fiscale Annuo")
_ANNUAL_INPS_ROW_NORM = normalize_label("Imp. INPS Progr.")

# Soglie x0 (punto medio tra le etichette adiacenti) calibrate su entrambi i
# file di tredicesima noti - stesso layout fisico dei due box.
_ANNUAL_TAX_ZONES: list[tuple[float, str]] = [
    (478.0, "imposta_pagata_annua"),
    (374.0, "imposta_dovuta_annua"),
    (259.0, "imposta_lorda_annua"),
    (121.0, "imponibile_fiscale_annuo"),
    (0.0, "retribuzione_utile_tfr_annua"),
]
_ANNUAL_INPS_ZONES: list[tuple[float, str]] = [
    (236.0, "cong_debito_annuo"),
    (182.0, "cong_credito_annuo"),
    (121.0, "ctr_dip_inps_progr_annuo"),
    (57.0, "ctr_inps_progr_annuo"),
    (0.0, "imp_inps_progr_annuo"),
]
_ANNUAL_TFR_FIELDS = {"retribuzione_utile_tfr_annua"}


def _extract_annual_summary(rows: list[Row]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Ritorna (campi_tax, campi_tfr) del riepilogo annuale. I valori del box
    "Imposta Dovuta"/"Cong. Credito"/"Cong. Debito" risultano assenti (non
    stampati, non zero-riempiti) su entrambi i campioni noti - il matching
    per posizione li lascia correttamente a None invece di disallinearli
    sugli altri campi presenti."""
    tax_values: dict[str, Decimal] = {}
    tfr_values: dict[str, Decimal] = {}
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        if i + 1 >= len(rows):
            continue
        if _ANNUAL_TAX_ROW_NORM in norm:
            zones = _ANNUAL_TAX_ZONES
        elif _ANNUAL_INPS_ROW_NORM in norm:
            zones = _ANNUAL_INPS_ZONES
        else:
            continue
        for w in rows[i + 1].words:
            amount = parse_amount(w.text)
            if amount is None:
                continue
            field = _column_of(w.x0, zones)
            if field is None:
                continue
            if field in _ANNUAL_TFR_FIELDS:
                tfr_values[field] = amount
            else:
                tax_values[field] = amount
    return tax_values, tfr_values


# --- Totali / IBAN / NETTO -----------------------------------------------

_TOTALE_TRATTENUTE_COMPETENZE_NORM = normalize_label("Totale Trattenute Totale Competenze")
_IBAN_RE = re.compile(r"^IT\d{2}[A-Z]\d{22}$")


def _amount_below_label(
    words: list[Word], label_x0: float, label_top: float, x_pad: float, max_dy: float
) -> Decimal | None:
    """Cerca l'importo piu' vicino (per top) sotto un'etichetta, entro una
    finestra di coordinate (x0 +/- x_pad, top in (label_top, label_top+max_dy]),
    lavorando sulle Word della pagina intera e non sulle Row: il valore di
    NETTO (§2.2 del piano) e' fuori riga rispetto alla propria etichetta e il
    clustering per riga lo aggrega alla riga dei valori T.F.R."""
    candidates = [
        w
        for w in words
        if label_top < w.top <= label_top + max_dy
        and abs(w.x0 - label_x0) <= x_pad
        and parse_amount(w.text) is not None
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda w: w.top)
    return parse_amount(candidates[0].text)


def _extract_totals(rows: list[Row], page_words: list[Word]) -> PayrollTotalsDTO:
    totals = PayrollTotalsDTO()
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        if _TOTALE_TRATTENUTE_COMPETENZE_NORM in norm:
            for next_row in rows[i + 1 : i + 4]:
                amounts = [w for w in next_row.words if parse_amount(w.text) is not None]
                trattenute_vals = [w for w in amounts if w.x0 < COMPETENZE_MIN]
                competenze_vals = [w for w in amounts if w.x0 >= COMPETENZE_MIN]
                if trattenute_vals:
                    totals.totale_trattenute = parse_amount(trattenute_vals[0].text)
                if competenze_vals:
                    totals.totale_competenze = parse_amount(competenze_vals[0].text)
                if trattenute_vals or competenze_vals:
                    break
            break

    for w in page_words:
        if _IBAN_RE.match(w.text):
            totals.iban = w.text
            break

    netto_word = next((w for w in page_words if w.text == "NETTO"), None)
    if netto_word is not None:
        totals.netto_mese = _amount_below_label(
            page_words, netto_word.x0, netto_word.top, x_pad=30.0, max_dy=35.0
        )
    return totals


def map_document(doc: RawExtractedDocument) -> PayrollDocumentDTO:
    all_rows = [r for p in doc.pages for r in p.rows]
    all_words = [w for p in doc.pages for w in p.words]

    company, employee, hire_date_str = _parse_header(doc.first_page.rows)

    codice_fiscale_originale = employee.codice_fiscale
    codice_fiscale_non_valido = bool(employee.codice_fiscale) and not codice_fiscale_checksum_valido(
        employee.codice_fiscale
    )
    if codice_fiscale_non_valido:
        employee.codice_fiscale = ""

    pay_lines: list[PayLineDTO] = []
    unmapped_rows: list[str] = []
    for page in doc.pages:
        p_lines, p_unmapped = _extract_pay_lines_from_page(page.rows)
        pay_lines.extend(p_lines)
        unmapped_rows.extend(p_unmapped)

    tax = _extract_tax(all_rows)
    tfr = _extract_tfr(all_rows)
    leave_balances = _extract_leave_balances(all_rows)
    totals = _extract_totals(all_rows, all_words)

    annual_tax_values, annual_tfr_values = _extract_annual_summary(all_rows)
    for field, amount in annual_tax_values.items():
        setattr(tax, field, amount)
    for field, amount in annual_tfr_values.items():
        setattr(tfr, field, amount)

    period_type, mese, anno, label_originale = _parse_period(doc.first_page.rows)
    if mese == 0:
        period = PeriodDTO(
            mese=0,
            anno=0,
            tipo=period_type,
            label_originale=label_originale,
            classification=DataClassification.NON_RICONOSCIUTO,
        )
    else:
        period = PeriodDTO(mese=mese, anno=anno, tipo=period_type, label_originale=label_originale)

    hire_date = _parse_date_slash(hire_date_str) if hire_date_str else None

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
                    "check-digit ufficiale - trattato come non riconosciuto, verificare manualmente"
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
                messaggio=f"Periodo non riconosciuto dal testo: {label_originale!r}",
                campo="period",
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
    if any(p.recovered_from_scramble for p in doc.pages):
        dto.anomalies.append(
            AnomalyDTO(
                tipo="testo_ricostruito",
                severita=AnomalySeverity.WARNING,
                messaggio=(
                    "Testo ricostruito dall'ordine di stream (font a avanzamento zero, mai osservato "
                    "sui campioni SAP HR noti): verificare gli importi"
                ),
                campo=None,
            )
        )
    if totals.iban and not iban_mod97_valid(totals.iban):
        dto.anomalies.append(
            AnomalyDTO(
                tipo="iban_non_valido",
                severita=AnomalySeverity.WARNING,
                messaggio=f"IBAN {totals.iban!r} non supera il checksum mod-97: verificare manualmente",
                campo="totals.iban",
            )
        )
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


SPEC = TemplateSpec(name=TEMPLATE_NAME, parser_version=PARSER_VERSION, detect=is_sap_hr_document, map=map_document)