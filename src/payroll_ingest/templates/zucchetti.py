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

TEMPLATE_NAME = "zucchetti_standard"
PARSER_VERSION = "1.0.0"

_CODE_RE = re.compile(r"^[A-Z]{0,2}\d{4,6}$")
_COMPANY_CODE_ROW_RE = re.compile(r"^(\d{6})\s+([A-Z].{5,})$")
_ADDRESS_ROW_RE = re.compile(r"^(.*?)\s+Aut\.\s*(\S+)$")
_CAP_CITY_ROW_RE = re.compile(r"^(\d{5})\s+([A-Z].+\([A-Z]{2}\))$")
_DEL_SEDE_ROW_RE = re.compile(r"Del\s+(\S+)\s+Sede\s+(\S+)")
_COMPANY_CF_ROW_RE = re.compile(r"^(\d{11})\s+(\S+/\d{2})\s+(\S+/\d{2})$")
_EMPLOYEE_ROW_RE = re.compile(r"^(\d{7})\s+([A-ZÀ-Ü' ]+?)\s+([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])$")
_TWO_DATES_ROW_RE = re.compile(r"^(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})$")

_HEADER_MAX_TOP = 260.0

UNIT_TOKENS = {"GG", "ORE", "%"}
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


def _looks_like_data(text: str) -> bool:
    return text in UNIT_TOKENS or text in ("(", ")") or parse_amount(text) is not None


def _first_amount(words: list[Word]) -> Decimal | None:
    for w in words:
        if w.text in ("(", ")"):
            continue
        value = parse_amount(w.text)
        if value is not None:
            return abs(value)
    return None


def _split_amount_zone(words: list[Word]) -> tuple[Decimal | None, Decimal | None]:
    """Un valore tra parentesi e' sempre una trattenuta, indipendentemente dalla
    colonna x in cui il tipografo Zucchetti lo visualizza (spesso coincide con la
    fascia COMPETENZE). Senza parentesi, la colonna x decide (trattenute a sinistra
    di COMPETENZE_MIN, competenze da COMPETENZE_MIN in poi)."""
    has_parens = any(w.text in ("(", ")") for w in words)
    for w in words:
        if w.text in ("(", ")"):
            continue
        value = parse_amount(w.text)
        if value is None:
            continue
        value = abs(value)
        if has_parens or w.x0 < COMPETENZE_MIN:
            return value, None
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


def _parse_causale_row(row: Row) -> PayLineDTO | None:
    words = row.words
    idx = 0
    while idx < len(words) and words[idx].text == "*":
        idx += 1
    if idx >= len(words):
        return None
    code_word = words[idx]
    if not _CODE_RE.match(code_word.text):
        return None
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
    riferimento_words = [w for w in buckets["riferimento"] if w.text not in ("(", ")")]
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

    return PayLineDTO(
        codice=code_word.text,
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


def _extract_causale_rows(rows: list[Row]) -> tuple[list[PayLineDTO], list[str]]:
    """Analizza le righe voce dinamiche, delimitate tra l'intestazione colonne e
    'Retribuzione utile T.F.R.' (o il primo TOTALE, se il TFR non e' presente)."""
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
        return [], []

    pay_lines: list[PayLineDTO] = []
    unmapped: list[str] = []
    for row in rows[start_idx:end_idx]:
        line = _parse_causale_row(row)
        if line is not None:
            pay_lines.append(line)
        elif row.text.strip():
            unmapped.append(row.text)
    return pay_lines, unmapped


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
_TFR_COLUMN_MATCH_TOLERANCE = 60.0


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
            for value_word in rows[i + 1].words:
                amount = parse_amount(value_word.text)
                if amount is None:
                    continue
                nearest_x0, field = min(marker_positions, key=lambda m: abs(m[0] - value_word.x0))
                if abs(nearest_x0 - value_word.x0) <= _TFR_COLUMN_MATCH_TOLERANCE:
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


def _extract_totals(rows: list[Row]) -> PayrollTotalsDTO:
    totals = PayrollTotalsDTO()
    netto_label_norm = normalize_label("NETTO DEL MESE")
    for i, row in enumerate(rows):
        norm = normalize_label(row.text)
        # "in" e non "startswith": alcune etichette (es. "TOTALE COMPETENZE") sono
        # precedute sulla stessa riga da un titolo di sezione ("RATEI ...").
        if normalize_label("Imp. INPS") in norm:
            totals.imponibile_inps = _first_amount(row.words)
        elif normalize_label("Imp. INAIL") in norm:
            totals.imponibile_inail = _first_amount(row.words)
        elif normalize_label("TOTALE COMPETENZE") in norm:
            totals.totale_competenze = _first_amount(row.words)
        elif normalize_label("TOTALE TRATTENUTE") in norm:
            totals.totale_trattenute = _first_amount(row.words)
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
    return totals


def map_document(doc: RawExtractedDocument) -> PayrollDocumentDTO:
    page = doc.first_page
    rows = page.rows

    company, employee, hire_date_str, tipo_costo_text = _parse_header(rows)
    pay_lines, unmapped_rows = _extract_causale_rows(rows)
    tax = _extract_tax(pay_lines, rows)
    tfr = _extract_tfr(rows)
    leave_balances = _extract_leave_balances(rows)
    totals = _extract_totals(rows)

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

    if not employee.codice_fiscale:
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

    return dto
