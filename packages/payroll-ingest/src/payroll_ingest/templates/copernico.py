"""Template per i cedolini "Copernico" (CopernicoPaghe, datore precedente
ACCENTURE TECHNOLOGY SOLUTIONS SRL, periodo 2016-09 -> 2019-01, 32 file).
Layout a due colonne header separate (diverso da Zucchetti), corpo voci a
codice numerico 4 cifre, IBAN scomposto su piu' campi. V. analisi completa e
soglie x calibrate in docs/PIANO_TECNICO_NEW_TEMPLATES.md §2.1/§5.

I 12 file 2018-03 -> 2019-01 (font Win2PDF a avanzamento zero) arrivano qui
gia' ricostruiti da extraction.py (v. RawPage.recovered_from_scramble): questo
modulo non distingue i due casi, salvo segnalare l'anomalia informativa
"testo_ricostruito" quando il flag e' presente."""

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
    COLUMN_MATCH_TOLERANCE,
    PAREN_MARKERS,
    UNIT_TOKENS,
    codice_fiscale_checksum_valido,
    first_amount,
    iban_mod97_valid,
    match_column_values,
    rows_with_numeric_value,
)
from payroll_ingest.templates._spec import TemplateSpec

TEMPLATE_NAME = "copernico_paghe"
PARSER_VERSION = "1.0.0"

# --- Detection --------------------------------------------------------------

_HEADER_LABEL_NORM = normalize_label("Codice Azienda/Filiale/Stabil Ragione Sociale Azienda")
_FOOTER_MARKER_NORM = normalize_label("CPLUACC1")

# --- Header anagrafico --------------------------------------------------------

_HEADER_MAX_TOP = 150.0
_COMPANY_PREFIX_RE = re.compile(r"^ATS/\s*(\d+)\s*/\s*([A-Z]{2})\s+(.+)$")
_SLASH_CODE_RE = re.compile(r"^\d+/\d+$")
_NAME_WORD_RE = re.compile(r"^[A-ZÀ-Ü']+$")

# I campi CF/IBAN/periodo sono cercati sul testo di riga "compattato" (parole
# concatenate senza spazio), non parola-per-parola: sui file Win2PDF ricostruiti
# (v. extraction.py, WORD_X0_JUMP_TOLERANCE) alcuni token con un salto di x0
# interno superiore alla soglia finiscono spezzati su piu' Word (osservato su
# CF e nome del mese in 201804.pdf), e un semplice join con spazio (Row.text)
# introdurrebbe uno spazio spurio in mezzo al token, rompendo un match ancorato
# su un'unica parola o su una sequenza rigida di `\s*`.
def _compact(row: Row) -> str:
    return "".join(w.text for w in row.words)


_CF_COMPACT_RE = re.compile(r"[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]")
_DATE_SLASH_COMPACT_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")

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
_PERIOD_MESE_COMPACT_RE = re.compile(
    r"(Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|Luglio|Agosto|Settembre|Ottobre|Novembre|Dicembre)(\d{4})",
    re.IGNORECASE,
)
_PERIOD_TREDICESIMA_COMPACT_RE = re.compile(r"13[-]?esima(\d{4})", re.IGNORECASE)

# --- Corpo voci -----------------------------------------------------------

_VOCI_START_MARKER_A = normalize_label("Descrizione")
_VOCI_START_MARKER_B = normalize_label("Competenze")
_VOCI_END_NORM = normalize_label("Totale Ritenute Sociali")
# Prefisso lettera opzionale (es. "F2905 Contatore Premi in Natura al mese
# prec.", 5/57 file - issue #29) o interamente alfabetico (es. "CTRAGG
# Contributo Aggiuntivo"/"CTRAGG Conguaglio a credito CTRAGG", conguaglio
# raro ma con importo reale, 1/57 file - issue #30): non solo numerico a 4
# cifre come la maggioranza delle voci.
_CODICE_RE = re.compile(r"^([A-Z]?\d{4}|[A-Z]{5,8})$")
_FIGURATIVO_FLAG = "F"

# Trattenuta INPS Contributo FAP (Fondo Pensioni Complementare): riga a
# etichetta testuale fissa (aliquota 9,490 / imponibile / importo), non a
# codice causale a 4 cifre come le altre voci - presente su 20/20 cedolini
# Copernico verificati, mai mappata prima (issue GH #28).
_INPS_FAP_LABEL_NORM = normalize_label("INPS Contributo FAP")

# Soglie x0 calibrate su docs/new-templates/2016/201610.pdf (PDFsharp) e
# 2018/201804.pdf (Win2PDF ricostruito), v. piano §2.1. Il layout non cambia
# tra i due producer, solo il rendering del font. Tutto cio' che sta a sinistra
# di DATO_BASE_MIN e' la colonna Ore/GG (unica soglia inferiore necessaria: non
# esiste una quarta colonna oltre descrizione/ore-gg/dato-base/importo).
DATO_BASE_MIN = 345.0
RITENUTE_MIN = 420.0
COMPETENZE_MIN = 503.0
# Soglia description->dati: verificata sui 32 file Copernico che l'ultima
# parola di descrizione osservata sta a x0<=164.9 ("prec." di "F2905 Contatore
# Premi in Natura al mese prec.") e la prima colonna dati (Ore/GG) parte
# sempre da x0>=241.0, ampio margine su entrambi i lati - v. issue GH #29:
# usare il CONTENUTO della parola (era: prima parola che "sembra un dato",
# looks_like_data) tronca/svuota la descrizione quando questa contiene per
# caso un unit token ("ORE" in "0282 ORE STRAORD.60% MESE PRECEDENTE" o
# "0299 BANCA ORE GODUTE"), quindi il confine va deciso per POSIZIONE.
ORE_GG_MIN = 200.0

# --- Tax ------------------------------------------------------------------

_TAX_CODE_RE = re.compile(r"^(\d{4})(IM|RM)$")
_CVL_CODE_RE = re.compile(r"^CvL\d{3}$", re.IGNORECASE)
_RFVE_CODE_RE = re.compile(r"^RfVE\d{2}$", re.IGNORECASE)

# --- TFR --------------------------------------------------------------------

_TFR_BLOCK_A_MARKERS = [("retribuz", "retribuzione_utile_tfr")]
_TFR_BLOCK_B_MARKERS = [("accant", "quota_anno"), ("anticipazioni", "anticipi")]

# --- Ferie ------------------------------------------------------------------

_LEAVE_TYPES = ["ferie", "rol_ex_festivita", "banca_ore_riposi"]

# --- Totali / IBAN / NETTO -----------------------------------------------

_IBAN_CIN_EUR_RE = re.compile(r"^\d{2}$")
_IBAN_CIN_RE = re.compile(r"^[A-Z]$")
_IBAN_ABI_CAB_RE = re.compile(r"^\d{5}$")
_IBAN_CC_RE = re.compile(r"^\d{12}$")


def _find_iban_in_row(row: Row) -> str | None:
    """Cerca, in ordine sinistra->destra, le 5 parole che rispettano la forma
    cin_eur/cin/abi/cab/c-c (2 cifre, 1 lettera, 5 cifre, 5 cifre, 12 cifre),
    NON necessariamente consecutive: sui file puliti sono intervallate dalle
    etichette ("Paese IT Cin Eur 97 CIN E ABI 03111 ..."), mentre su alcuni
    Win2PDF le etichette finiscono su un Row distinto (salto di poco superiore
    a ROW_CLUSTER_TOLERANCE) e i 5 valori restano soli e consecutivi. La
    ricerca sequenziale (ogni pattern cercato solo DOPO la posizione del
    precedente) copre entrambi i casi senza doverli distinguere."""
    words = row.words

    def _next(pattern: re.Pattern[str], start: int) -> int | None:
        for j in range(start, len(words)):
            if pattern.match(words[j].text):
                return j
        return None

    idx = _next(_IBAN_CIN_EUR_RE, 0)
    if idx is None:
        return None
    cin_eur = words[idx].text

    idx = _next(_IBAN_CIN_RE, idx + 1)
    if idx is None:
        return None
    cin = words[idx].text

    idx = _next(_IBAN_ABI_CAB_RE, idx + 1)
    if idx is None:
        return None
    abi = words[idx].text

    idx = _next(_IBAN_ABI_CAB_RE, idx + 1)
    if idx is None:
        return None
    cab = words[idx].text

    idx = _next(_IBAN_CC_RE, idx + 1)
    if idx is None:
        return None
    cc = words[idx].text

    return f"IT{cin_eur}{cin}{abi}{cab}{cc}"


def is_copernico_document(doc: RawExtractedDocument) -> bool:
    page = doc.first_page
    header_rows = [row for row in page.rows if row.top < 30]
    if any(normalize_label(row.text).startswith(_HEADER_LABEL_NORM) for row in header_rows):
        return True
    # Marker di fondo pagina (footer "CopernicoPaghe S.r.l. CPLUACC1"): leggibile
    # anche sui Win2PDF ricostruiti, a differenza del solo header (doppio marker
    # per robustezza, v. piano §5).
    return any(_FOOTER_MARKER_NORM in normalize_label(row.text) for row in page.rows)


def _parse_company(rows: list[Row]) -> CompanyDTO:
    company = CompanyDTO(ragione_sociale="")
    for row in rows:
        m = _COMPANY_PREFIX_RE.match(row.text)
        if m:
            company.codice_azienda = f"ATS/{m.group(1)}/{m.group(2)}"
            company.ragione_sociale = m.group(3).strip()
            break
    return company


def _parse_matricola_and_name(row: Row) -> tuple[str | None, str | None]:
    words = row.words
    if not words or not _SLASH_CODE_RE.match(words[0].text):
        return None, None
    matricola = words[0].text.split("/")[0]
    name_words = []
    for w in words[1:]:
        if _NAME_WORD_RE.match(w.text):
            name_words.append(w.text)
        else:
            break
    cognome_nome = " ".join(name_words) if name_words else None
    return matricola, cognome_nome


def _parse_header(rows: list[Row]) -> tuple[CompanyDTO, EmployeeDTO, str | None]:
    header_rows = [r for r in rows if r.top < _HEADER_MAX_TOP]
    company = _parse_company(header_rows)

    matricola: str | None = None
    cognome_nome: str | None = None
    codice_fiscale = ""
    hire_date_str: str | None = None

    for row in header_rows:
        if matricola is None:
            m, n = _parse_matricola_and_name(row)
            if m is not None:
                matricola, cognome_nome = m, n
        if not codice_fiscale:
            compact = _compact(row)
            m = _CF_COMPACT_RE.search(compact)
            if m:
                codice_fiscale = m.group(0)
                # La riga del CF contiene anche Data Assunz./Data Cessaz./Data
                # Nascita nello stesso ordine di colonna; Data Cessaz. e' vuota
                # per un dipendente attivo (unico caso nei 32 campioni noti), per
                # cui la prima data presente e' sempre Data Assunz.
                dates = _DATE_SLASH_COMPACT_RE.findall(compact)
                if dates:
                    hire_date_str = dates[0]

    employee = EmployeeDTO(cognome_nome=cognome_nome or "", codice_fiscale=codice_fiscale, matricola=matricola)
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


def _parse_period(rows: list[Row]) -> tuple[PeriodType, int, int, str]:
    for row in rows:
        m = _PERIOD_TREDICESIMA_COMPACT_RE.search(_compact(row))
        if m:
            return PeriodType.MENSILITA_AGGIUNTIVA, 12, int(m.group(1)), m.group(0)
    for row in rows:
        m = _PERIOD_MESE_COMPACT_RE.search(_compact(row))
        if m:
            mese = _MESI_IT[m.group(1).lower()]
            return PeriodType.ORDINARIO, mese, int(m.group(2)), m.group(0)
    return PeriodType.ORDINARIO, 0, 0, ""


def _column_of(x0: float) -> str:
    if x0 >= RITENUTE_MIN:
        return "importo"
    if x0 >= DATO_BASE_MIN:
        return "dato_base"
    return "ore_gg"


def _split_amount_zone(words: list[Word]) -> tuple[Decimal | None, Decimal | None]:
    """Trattenute e competenze condividono la stessa fascia x0 (v. zucchetti.py
    per lo stesso pattern sul layout Zucchetti): un valore negativo/tra
    parentesi e' sempre una trattenuta, altrimenti decide la soglia
    COMPETENZE_MIN."""
    has_parens = any(w.text in PAREN_MARKERS for w in words)
    for w in words:
        if w.text in PAREN_MARKERS:
            continue
        value = parse_amount(w.text)
        if value is None:
            continue
        if has_parens or value < 0 or w.x0 < COMPETENZE_MIN:
            return abs(value), None
        return None, value
    return None, None


def _parse_pay_line_row(row: Row) -> PayLineDTO | None:
    words = row.words
    if not words or not _CODICE_RE.match(words[0].text):
        return None
    codice = words[0].text

    data_start = len(words)
    for i in range(1, len(words)):
        if words[i].x0 >= ORE_GG_MIN:
            data_start = i
            break
    desc_words = words[1:data_start]
    data_words = words[data_start:]

    descrizione = " ".join(w.text for w in desc_words).strip()
    if not descrizione:
        return None

    figurativo = bool(data_words) and data_words[-1].text == _FIGURATIVO_FLAG
    if figurativo:
        data_words = data_words[:-1]

    buckets: dict[str, list[Word]] = {"ore_gg": [], "dato_base": [], "importo": []}
    for w in data_words:
        buckets[_column_of(w.x0)].append(w)

    quantita = None
    aliquota = None
    unita = None
    ore_gg_words = [w for w in buckets["ore_gg"] if w.text not in PAREN_MARKERS]
    unit_words = [w for w in ore_gg_words if w.text in UNIT_TOKENS]
    numeric_words = [w for w in ore_gg_words if w.text not in UNIT_TOKENS]
    if unit_words:
        unita = unit_words[0].text
    if numeric_words:
        value = parse_amount(numeric_words[0].text)
        if unita == "%":
            aliquota = value
        else:
            quantita = value

    importo_base = first_amount(buckets["dato_base"]) if buckets["dato_base"] else None
    trattenuta, competenza = _split_amount_zone(buckets["importo"])

    return PayLineDTO(
        codice=codice,
        descrizione=descrizione,
        categoria=PayLineCategory.ALTRO,
        is_recognized=True,
        importo_base=importo_base,
        quantita=quantita,
        unita=unita,
        aliquota=aliquota,
        trattenuta=trattenuta,
        competenza=competenza,
        raw_text=row.text,
        note="valore esclusivamente figurativo (non concorre al netto)" if figurativo else None,
        classification=DataClassification.OPZIONALE,
    )


def _parse_inps_fap_row(row: Row) -> PayLineDTO | None:
    """Riga a etichetta fissa 'INPS Contributo FAP' seguita da tre importi
    (aliquota, imponibile, importo trattenuto), non dal codice causale a 4
    cifre delle altre voci - v. _INPS_FAP_LABEL_NORM."""
    if not normalize_label(row.text).startswith(_INPS_FAP_LABEL_NORM):
        return None
    amounts = [v for w in row.words if (v := parse_amount(w.text)) is not None]
    if len(amounts) < 3:
        return None
    aliquota, imponibile, importo = amounts[0], amounts[1], amounts[2]
    return PayLineDTO(
        codice=None,
        descrizione="INPS Contributo FAP",
        categoria=PayLineCategory.CONTRIBUTO,
        is_recognized=True,
        importo_base=abs(imponibile),
        aliquota=aliquota,
        trattenuta=abs(importo),
        raw_text=row.text,
        classification=DataClassification.OPZIONALE,
    )


def _extract_pay_lines_from_page(rows: list[Row]) -> tuple[list[PayLineDTO], list[str]]:
    pay_lines: list[PayLineDTO] = []
    unmapped: list[str] = []
    in_section = False
    for row in rows:
        norm = normalize_label(row.text)
        if not in_section:
            if _VOCI_START_MARKER_A in norm and _VOCI_START_MARKER_B in norm:
                in_section = True
            continue
        if _VOCI_END_NORM in norm:
            break
        parsed = _parse_pay_line_row(row) or _parse_inps_fap_row(row)
        if parsed is not None:
            pay_lines.append(parsed)
        elif row.text.strip():
            unmapped.append(row.text)
    return pay_lines, unmapped


def _extract_tax(rows: list[Row]) -> TaxDTO:
    tax = TaxDTO()
    for row in rows:
        words = row.words
        if not words:
            continue
        first = words[0].text
        m = _TAX_CODE_RE.match(first)
        if m:
            amount = first_amount(words[1:])
            if m.group(2) == "IM":
                tax.imponibile_irpef = amount
            else:
                tax.irpef_lorda = amount
            continue
        if first.upper() == "DETRFI":
            tax.detrazioni_lav_dip = first_amount(words[1:])
            continue
        if first.upper() == "IRPEF":
            tax.ritenute_irpef = first_amount(words[1:])
            continue
        if _CVL_CODE_RE.match(first):
            if len(words) > 1 and words[1].text.upper() == "AC":
                tax.acconto_addizionale_comunale = first_amount(words[2:])
            else:
                tax.addizionale_comunale = first_amount(words[1:])
            continue
        if _RFVE_CODE_RE.match(first):
            tax.addizionale_regionale = first_amount(words[1:])
            continue
    return tax


def _extract_tfr(rows: list[Row]) -> TfrDTO:
    tfr = TfrDTO()
    for i, row in enumerate(rows):
        lowered = row.text.lower()
        if "retribuz" in lowered and "tfr" in lowered and i + 1 < len(rows):
            marker_positions = [
                (w.x0, field) for w in row.words for marker, field in _TFR_BLOCK_A_MARKERS if marker in w.text.lower()
            ]
            if marker_positions:
                values = match_column_values(marker_positions, rows[i + 1].words, COLUMN_MATCH_TOLERANCE)
                for field, amount in values.items():
                    setattr(tfr, field, amount)
            break
    for i, row in enumerate(rows):
        lowered = row.text.lower()
        if "accant" in lowered and "anticipazioni" in lowered and i + 1 < len(rows):
            marker_positions = [
                (w.x0, field) for w in row.words for marker, field in _TFR_BLOCK_B_MARKERS if marker in w.text.lower()
            ]
            if marker_positions:
                values = match_column_values(marker_positions, rows[i + 1].words, COLUMN_MATCH_TOLERANCE)
                for field, amount in values.items():
                    setattr(tfr, field, amount)
            break
    return tfr


_LEAVE_HEADER_SPETTANTI_NORM = normalize_label("Spettanti")
_LEAVE_HEADER_GODUTE_NORM = normalize_label("Godute")
_LEAVE_HEADER_RESIDUE_NORM = normalize_label("Residue")


def _extract_leave_balances(rows: list[Row]) -> list[LeaveBalanceDTO]:
    header_idx = None
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        if (
            _LEAVE_HEADER_SPETTANTI_NORM in norm
            and _LEAVE_HEADER_GODUTE_NORM in norm
            and _LEAVE_HEADER_RESIDUE_NORM in norm
        ):
            header_idx = i
            break
    if header_idx is None:
        return []

    value_rows: dict[str, Row] = {}
    for row in rows[header_idx + 1 : header_idx + 6]:
        if not row.words:
            continue
        label = row.words[0].text.upper()
        if label in ("AC", "AP", "AP2") and label not in value_rows:
            value_rows[label] = row

    ac_row = value_rows.get("AC")
    if ac_row is None:
        return []

    def amounts(row: Row | None) -> list[Decimal | None]:
        if row is None:
            return [None] * 9
        vals = [parse_amount(w.text) for w in row.words[1:]]
        return (vals + [None] * 9)[:9]

    ac_vals = amounts(ac_row)
    ap_vals = amounts(value_rows.get("AP"))
    ap2_vals = amounts(value_rows.get("AP2"))

    balances: list[LeaveBalanceDTO] = []
    for i, tipo in enumerate(_LEAVE_TYPES):
        maturato, goduto, residuo = ac_vals[i * 3], ac_vals[i * 3 + 1], ac_vals[i * 3 + 2]
        residuo_ap = ap_vals[i * 3 + 2]
        if maturato is None and goduto is None and residuo is None and residuo_ap is None:
            continue
        balances.append(
            LeaveBalanceDTO(tipo=tipo, maturato=maturato, goduto=goduto, residuo=residuo, residuo_ap=residuo_ap)
        )
        residuo_ap2 = ap2_vals[i * 3 + 2]
        if residuo_ap2 is not None and residuo_ap2 != 0:
            balances.append(LeaveBalanceDTO(tipo=f"{tipo}_ap2", residuo=residuo_ap2))
    return balances


def _extract_totals(rows: list[Row]) -> PayrollTotalsDTO:
    totals = PayrollTotalsDTO()
    tot_ritenute_norm = normalize_label("Totale Ritenute")
    tot_competenze_norm = normalize_label("Totale Competenze")
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        if tot_ritenute_norm in norm and tot_competenze_norm in norm and i + 1 < len(rows):
            value_words = [w for w in rows[i + 1].words if parse_amount(w.text) is not None]
            if len(value_words) >= 2:
                totals.totale_trattenute = parse_amount(value_words[0].text)
                totals.totale_competenze = parse_amount(value_words[-1].text)
            elif len(value_words) == 1:
                totals.totale_competenze = parse_amount(value_words[0].text)
        if "netto" in norm and "pagare" in norm:
            # I valori IBAN sono di norma sulla stessa riga di "NETTO A PAGARE",
            # ma su alcuni Win2PDF finiscono sulla riga immediatamente
            # precedente (etichette e valori separati da un salto di top di
            # poco superiore a ROW_CLUSTER_TOLERANCE, v. _find_iban_in_row).
            candidate_rows = [row] + ([rows[i - 1]] if i > 0 else [])
            for candidate in candidate_rows:
                iban = _find_iban_in_row(candidate)
                if iban is not None:
                    totals.iban = iban
                    break
            for next_row in rows[i + 1 : i + 5]:
                amount = first_amount(next_row.words)
                if amount is not None:
                    totals.netto_mese = amount
                    break
    return totals


def map_document(doc: RawExtractedDocument) -> PayrollDocumentDTO:
    all_rows = [r for p in doc.pages for r in p.rows]

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
    totals = _extract_totals(all_rows)

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
    righe_con_importo = rows_with_numeric_value(unmapped_rows)
    if righe_con_importo:
        dto.anomalies.append(
            AnomalyDTO(
                tipo="righe_non_mappate",
                severita=AnomalySeverity.INFO,
                messaggio=(
                    f"{len(righe_con_importo)} righe con importo non mappate "
                    f"(su {len(unmapped_rows)} righe totali non riconosciute nella sezione voci)"
                ),
                campo="pay_lines",
            )
        )
    if any(p.recovered_from_scramble for p in doc.pages):
        dto.anomalies.append(
            AnomalyDTO(
                tipo="testo_ricostruito",
                severita=AnomalySeverity.WARNING,
                messaggio=(
                    "Testo ricostruito dall'ordine di stream (font Win2PDF a avanzamento zero, "
                    "v. docs/PIANO_TECNICO_NEW_TEMPLATES.md §3): verificare gli importi"
                ),
                campo=None,
            )
        )
    if totals.iban and not iban_mod97_valid(totals.iban):
        dto.anomalies.append(
            AnomalyDTO(
                tipo="iban_non_valido",
                severita=AnomalySeverity.WARNING,
                messaggio=f"IBAN ricomposto {totals.iban!r} non supera il checksum mod-97: verificare manualmente",
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


SPEC = TemplateSpec(name=TEMPLATE_NAME, parser_version=PARSER_VERSION, detect=is_copernico_document, map=map_document)
