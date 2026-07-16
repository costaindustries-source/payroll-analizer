"""Suite di copertura per il template Copernico (packages/payroll-ingest/src/
payroll_ingest/templates/copernico.py). Nessun PDF reale: Row/Word sintetici
come nel resto della suite (i campioni reali sono gitignored, dati personali),
stesso stile di test_zucchetti_mapping.py."""

from decimal import Decimal
from pathlib import Path

from payroll_ingest.dto import PeriodType
from payroll_ingest.extraction import RawExtractedDocument, RawPage, Row, Word
from payroll_ingest.templates import copernico as c
from payroll_ingest.templates._common import iban_mod97_valid


def w(text: str, x0: float, top: float = 100.0) -> Word:
    return Word(text=text, x0=x0, x1=x0 + len(text) * 5 + 2, top=top, bottom=top + 10)


def trow(top: float, text: str) -> Row:
    x = 20.0
    words = []
    for token in text.split(" "):
        words.append(w(token, x, top))
        x += len(token) * 5 + 10
    return Row(top=top, words=words)


def _page(rows: list[Row]) -> RawPage:
    return RawPage(words=[], rows=rows, full_text="", width=600.0, height=800.0)


def _doc(rows: list[Row], extra_pages: list[list[Row]] | None = None) -> RawExtractedDocument:
    pages = [_page(rows)] + [_page(r) for r in (extra_pages or [])]
    return RawExtractedDocument(source_path=Path("sintetico.pdf"), pages=pages)


def _iban_parts_valido() -> tuple[str, str, str, str, str]:
    abi, cab, cc, cin = "03111", "11706", "000000012863", "E"
    for cin_eur in range(100):
        candidate = f"IT{cin_eur:02d}{cin}{abi}{cab}{cc}"
        if iban_mod97_valid(candidate):
            return f"{cin_eur:02d}", cin, abi, cab, cc
    raise AssertionError("nessun IBAN sintetico checksum-valido trovato")


CF_VALIDO = "RSSMRA80A01H501U"
CF_CHECKSUM_ERRATO = "RSSMRA80A01H501A"


# ---------------------------------------------------------------------------
# is_copernico_document
# ---------------------------------------------------------------------------


def test_is_copernico_document_riconosce_header():
    doc = _doc([trow(10.0, "Codice Azienda/Filiale/Stabil Ragione Sociale Azienda")])
    assert c.is_copernico_document(doc) is True


def test_is_copernico_document_riconosce_footer_marker():
    doc = _doc([trow(800.0, "CPLUACC1 F=VALORE ESCLUSIVAMENTE FIGURATIVO")])
    assert c.is_copernico_document(doc) is True


def test_is_copernico_document_non_riconosciuto():
    doc = _doc([trow(10.0, "Documento Generico")])
    assert c.is_copernico_document(doc) is False


# ---------------------------------------------------------------------------
# _parse_company / _parse_matricola_and_name / _parse_header
# ---------------------------------------------------------------------------


def test_parse_company_estrae_codice_e_ragione_sociale():
    rows = [trow(34.0, "ATS/ 01/ VR ACCENTURE TECHNOLOGY SOLUTIONS SRL")]
    company = c._parse_company(rows)
    assert company.codice_azienda == "ATS/01/VR"
    assert company.ragione_sociale == "ACCENTURE TECHNOLOGY SOLUTIONS SRL"


def test_parse_company_nessun_match_resta_vuota():
    company = c._parse_company([trow(34.0, "Riga qualunque")])
    assert company.ragione_sociale == ""


def test_parse_matricola_and_name_riga_valida():
    row = Row(top=60.0, words=[w("7516/80007516", 30), w("ROSSI", 150), w("MARIO", 250), w("Altro", 350)])
    matricola, nome = c._parse_matricola_and_name(row)
    assert matricola == "7516"
    assert nome == "ROSSI MARIO"


def test_parse_matricola_and_name_riga_non_matricola():
    row = Row(top=60.0, words=[w("Comune", 30), w("Residenza", 100)])
    assert c._parse_matricola_and_name(row) == (None, None)


def test_parse_header_estrae_tutti_i_campi():
    rows = [
        trow(20.0, "Codice Azienda/Filiale/Stabil Ragione Sociale Azienda"),
        trow(34.0, "ATS/ 01/ VR ACCENTURE TECHNOLOGY SOLUTIONS SRL"),
        trow(60.0, "7516/80007516 ROSSI MARIO"),
        trow(107.0, f"37124 VERONA 13600/22274764-04 04/07/2016 23/04/1991 {CF_VALIDO} del"),
    ]
    company, employee, hire_date_str = c._parse_header(rows)
    assert company.ragione_sociale == "ACCENTURE TECHNOLOGY SOLUTIONS SRL"
    assert employee.matricola == "7516"
    assert employee.cognome_nome == "ROSSI MARIO"
    assert employee.codice_fiscale == CF_VALIDO
    assert hire_date_str == "04/07/2016"


def test_parse_header_cf_frammentato_su_piu_parole():
    # Simula la frammentazione osservata sui Win2PDF ricostruiti (v.
    # WORD_X0_JUMP_TOLERANCE in extraction.py): il CF finisce spezzato su due
    # Word distinte, senza alcuno spazio "vero" tra i due pezzi.
    cf_parte1, cf_parte2 = CF_VALIDO[:6], CF_VALIDO[6:]
    rows = [trow(107.0, f"{cf_parte1} {cf_parte2}")]
    _, employee, _ = c._parse_header(rows)
    assert employee.codice_fiscale == CF_VALIDO


def test_parse_header_righe_assenti_lascia_campi_vuoti():
    company, employee, hire_date_str = c._parse_header([])
    assert company.ragione_sociale == ""
    assert employee.codice_fiscale == ""
    assert employee.matricola is None
    assert hire_date_str is None


# ---------------------------------------------------------------------------
# _parse_date_slash
# ---------------------------------------------------------------------------


def test_parse_date_slash_giorno_singola_cifra():
    d = c._parse_date_slash("04/07/2016")
    assert d is not None
    assert (d.year, d.month, d.day) == (2016, 7, 4)


def test_parse_date_slash_formato_non_valido():
    assert c._parse_date_slash("non una data") is None


def test_parse_date_slash_data_calendariale_non_valida():
    assert c._parse_date_slash("31/11/2020") is None


# ---------------------------------------------------------------------------
# _parse_period
# ---------------------------------------------------------------------------


def test_parse_period_ordinario_senza_spazio():
    tipo, mese, anno, label = c._parse_period([trow(148.0, "Ottobre2016")])
    assert tipo == PeriodType.ORDINARIO
    assert (mese, anno) == (10, 2016)
    assert label == "Ottobre2016"


def test_parse_period_tredicesima():
    tipo, mese, anno, _label = c._parse_period([trow(148.0, "13-esima2016")])
    assert tipo == PeriodType.MENSILITA_AGGIUNTIVA
    assert (mese, anno) == (12, 2016)


def test_parse_period_non_riconosciuto():
    tipo, mese, anno, label = c._parse_period([trow(148.0, "testo qualunque")])
    assert tipo == PeriodType.ORDINARIO
    assert (mese, anno) == (0, 0)
    assert label == ""


# ---------------------------------------------------------------------------
# _column_of / _split_amount_zone
# ---------------------------------------------------------------------------


def test_column_of_soglie():
    assert c._column_of(c.RITENUTE_MIN) == "importo"
    assert c._column_of(c.DATO_BASE_MIN) == "dato_base"
    assert c._column_of(0.0) == "ore_gg"


def test_split_amount_zone_parentesi_e_trattenuta():
    words = [w("(", 400), w("100,00", 410), w(")", 460)]
    trattenuta, competenza = c._split_amount_zone(words)
    assert trattenuta == Decimal("100.00")
    assert competenza is None


def test_split_amount_zone_sopra_soglia_competenze():
    words = [w("500,00", 510)]
    trattenuta, competenza = c._split_amount_zone(words)
    assert trattenuta is None
    assert competenza == Decimal("500.00")


def test_split_amount_zone_vuota():
    assert c._split_amount_zone([]) == (None, None)


def test_split_amount_zone_ignora_token_non_numerico_prima_del_vero_importo():
    words = [w("N/A", 400), w("500,00", 510)]
    trattenuta, competenza = c._split_amount_zone(words)
    assert trattenuta is None
    assert competenza == Decimal("500.00")


# ---------------------------------------------------------------------------
# _parse_pay_line_row
# ---------------------------------------------------------------------------


def test_parse_pay_line_row_retribuzione_ordinaria():
    row = Row(
        top=264.0,
        words=[
            w("0001", 20),
            w("RETRIBUZIONE", 55),
            w("ORDINARIA", 115),
            w("26,00", 241),
            w("1.500,00", 374),
            w("1.500,00", 529),
        ],
    )
    line = c._parse_pay_line_row(row)
    assert line is not None
    assert line.codice == "0001"
    assert line.descrizione == "RETRIBUZIONE ORDINARIA"
    assert line.quantita == Decimal("26.00")
    assert line.importo_base == Decimal("1500.00")
    assert line.competenza == Decimal("1500.00")
    assert line.note is None


def test_parse_pay_line_row_aliquota_percentuale():
    row = Row(top=100.0, words=[w("1234", 20), w("Ctr.prev", 55), w("9,19", 250), w("%", 280)])
    line = c._parse_pay_line_row(row)
    assert line is not None
    assert line.aliquota == Decimal("9.19")
    assert line.quantita is None


def test_parse_pay_line_row_flag_figurativo():
    row = Row(
        top=275.0,
        words=[w("1542", 20), w("ACCANTONAMENTO", 55), w("T.F.R.", 140), w("500,00", 536), w("F", 565)],
    )
    line = c._parse_pay_line_row(row)
    assert line is not None
    assert line.note == "valore esclusivamente figurativo (non concorre al netto)"
    assert line.competenza == Decimal("500.00")


def test_parse_pay_line_row_senza_codice_valido():
    row = Row(top=100.0, words=[w("Imponibile", 55), w("Previdenziale", 100)])
    assert c._parse_pay_line_row(row) is None


def test_parse_pay_line_row_codice_con_prefisso_lettera():
    # "F2905 Contatore Premi in Natura al mese prec. 75,00 F" (5/57 file, issue #29):
    # codice alfanumerico, non solo numerico a 4 cifre.
    row = Row(
        top=100.0,
        words=[
            w("F2905", 28.8),
            w("Contatore", 55.0),
            w("Premi", 87.6),
            w("in", 108.0),
            w("Natura", 115.9),
            w("al", 139.7),
            w("mese", 147.3),
            w("prec.", 164.9),
            w("75,00", 540.7),
            w("F", 565.0),
        ],
    )
    line = c._parse_pay_line_row(row)
    assert line is not None
    assert line.codice == "F2905"
    assert line.descrizione == "Contatore Premi in Natura al mese prec."
    assert line.competenza == Decimal("75.00")
    assert line.note == "valore esclusivamente figurativo (non concorre al netto)"


def test_parse_pay_line_row_unit_token_nella_descrizione_non_la_tronca():
    # "0282 ORE STRAORD.60% MESE PRECEDENTE 1,00 21,34289 21,34" (issue #29):
    # "ORE" e' un unit token (v. UNIT_TOKENS) ma qui e' parte della descrizione,
    # non del dato - il confine descrizione/dati va deciso per posizione (x0),
    # non per contenuto della parola, altrimenti la riga risulta senza
    # descrizione e viene scartata per intero.
    row = Row(
        top=100.0,
        words=[
            w("0282", 30.7),
            w("ORE", 55.0),
            w("STRAORD.60%", 72.7),
            w("MESE", 128.1),
            w("PRECEDENTE", 150.9),
            w("1,00", 243.4),
            w("21,34289", 373.9),
            w("21,34", 540.7),
        ],
    )
    line = c._parse_pay_line_row(row)
    assert line is not None
    assert line.descrizione == "ORE STRAORD.60% MESE PRECEDENTE"
    assert line.quantita == Decimal("1.00")
    assert line.competenza == Decimal("21.34")


def test_parse_pay_line_row_unit_token_nella_descrizione_non_confuso_con_dato_base():
    # "0299 BANCA ORE GODUTE 4,00 F": stesso rischio del caso precedente ma
    # senza fallire del tutto - con il vecchio confine per contenuto la
    # descrizione risultava troncata a "BANCA" invece di "BANCA ORE GODUTE".
    row = Row(
        top=100.0,
        words=[w("0299", 30.7), w("BANCA", 55.0), w("ORE", 84.2), w("GODUTE", 102.0), w("4,00", 243.4), w("F", 565.0)],
    )
    line = c._parse_pay_line_row(row)
    assert line is not None
    assert line.descrizione == "BANCA ORE GODUTE"
    assert line.quantita == Decimal("4.00")


def test_parse_pay_line_row_senza_descrizione():
    row = Row(top=100.0, words=[w("0001", 20), w("1.500,00", 374)])
    assert c._parse_pay_line_row(row) is None


# ---------------------------------------------------------------------------
# _parse_inps_fap_row
# ---------------------------------------------------------------------------


def test_parse_inps_fap_row_riconosce_pattern():
    row = trow(310.0, "INPS Contributo FAP 9,490 2.324,00000 220,55")
    line = c._parse_inps_fap_row(row)
    assert line is not None
    assert line.codice is None
    assert line.descrizione == "INPS Contributo FAP"
    assert line.categoria.value == "contributo"
    assert line.aliquota == Decimal("9.490")
    assert line.importo_base == Decimal("2324.00000")
    assert line.trattenuta == Decimal("220.55")


def test_parse_inps_fap_row_etichetta_diversa_non_matcha():
    row = trow(100.0, "Imponibile Previdenziale Non Arrotondato 2.324,37")
    assert c._parse_inps_fap_row(row) is None


def test_parse_inps_fap_row_meno_di_tre_importi_non_matcha():
    row = trow(100.0, "INPS Contributo FAP 9,490")
    assert c._parse_inps_fap_row(row) is None


# ---------------------------------------------------------------------------
# _extract_pay_lines_from_page
# ---------------------------------------------------------------------------


def test_extract_pay_lines_from_page_delimita_sezione_e_scarta_boilerplate():
    rows = [
        trow(255.0, "Cod. Descrizione Ore/GG % Dato Base Ritenute Competenze"),
        Row(top=264.0, words=[w("0001", 20), w("RETRIBUZIONE", 55), w("1.500,00", 529)]),
        trow(300.0, "Imponibile Previdenziale Non Arrotondato"),
        trow(325.0, "Totale Ritenute Sociali"),
        trow(338.0, "1001IM Imponibile Fiscale Mese"),
    ]
    pay_lines, unmapped = c._extract_pay_lines_from_page(rows)
    assert len(pay_lines) == 1
    assert pay_lines[0].codice == "0001"
    assert unmapped == ["Imponibile Previdenziale Non Arrotondato"]


def test_extract_pay_lines_from_page_riconosce_riga_inps_fap():
    rows = [
        trow(255.0, "Cod. Descrizione Ore/GG % Dato Base Ritenute Competenze"),
        Row(top=264.0, words=[w("0001", 20), w("RETRIBUZIONE", 55), w("1.500,00", 529)]),
        trow(310.0, "INPS Contributo FAP 9,490 2.324,00000 220,55"),
        trow(325.0, "Totale Ritenute Sociali"),
    ]
    pay_lines, unmapped = c._extract_pay_lines_from_page(rows)
    assert len(pay_lines) == 2
    assert pay_lines[1].descrizione == "INPS Contributo FAP"
    assert unmapped == []


def test_extract_pay_lines_from_page_senza_header_restituisce_vuoto():
    pay_lines, unmapped = c._extract_pay_lines_from_page([trow(100.0, "riga qualunque")])
    assert pay_lines == []
    assert unmapped == []


# ---------------------------------------------------------------------------
# _extract_tax
# ---------------------------------------------------------------------------


def test_extract_tax_mappa_tutti_i_codici_noti():
    rows = [
        Row(top=0.0, words=[]),
        Row(top=1.0, words=[w("1001IM", 20), w("Imponibile", 55), w("2.000,00", 400)]),
        Row(top=2.0, words=[w("1001RM", 20), w("Ritenuta", 55), w("300,00", 400)]),
        Row(top=3.0, words=[w("DETRFI", 20), w("Detrazioni", 55), w("50,00", 400)]),
        Row(top=4.0, words=[w("IRPeF", 20), w("Ritenuta", 55), w("250,00", 400)]),
        Row(top=5.0, words=[w("CvL001", 20), w("AC", 55), w("10,00", 400)]),
        Row(top=6.0, words=[w("CvL002", 20), w("Addiz.comunale", 55), w("20,00", 400)]),
        Row(top=7.0, words=[w("RfVE01", 20), w("Addiz.regionale", 55), w("30,00", 400)]),
    ]
    tax = c._extract_tax(rows)
    assert tax.imponibile_irpef == Decimal("2000.00")
    assert tax.irpef_lorda == Decimal("300.00")
    assert tax.detrazioni_lav_dip == Decimal("50.00")
    assert tax.ritenute_irpef == Decimal("250.00")
    assert tax.acconto_addizionale_comunale == Decimal("10.00")
    assert tax.addizionale_comunale == Decimal("20.00")
    assert tax.addizionale_regionale == Decimal("30.00")


def test_extract_tax_senza_dati_resta_tutto_none():
    tax = c._extract_tax([trow(1.0, "riga qualunque")])
    assert tax.imponibile_irpef is None
    assert tax.addizionale_regionale is None


# ---------------------------------------------------------------------------
# _extract_tfr
# ---------------------------------------------------------------------------


def test_extract_tfr_blocco_a_e_blocco_b():
    rows = [
        Row(top=1.0, words=[w("Retribuz.", 20), w("Utile", 60), w("TFR", 100)]),
        Row(top=2.0, words=[w("1.000,00", 40)]),
        Row(top=3.0, words=[w("Accant.TFR", 400), w("AC", 460), w("Anticipazioni", 500)]),
        Row(top=4.0, words=[w("200,00", 400), w("50,00", 500)]),
    ]
    tfr = c._extract_tfr(rows)
    assert tfr.retribuzione_utile_tfr == Decimal("1000.00")
    assert tfr.quota_anno == Decimal("200.00")
    assert tfr.anticipi == Decimal("50.00")


def test_extract_tfr_senza_dati_resta_tutto_none():
    tfr = c._extract_tfr([trow(1.0, "riga qualunque")])
    assert tfr.retribuzione_utile_tfr is None
    assert tfr.quota_anno is None


# ---------------------------------------------------------------------------
# _extract_leave_balances
# ---------------------------------------------------------------------------


def test_extract_leave_balances_righe_ac_ap_ap2():
    rows = [
        trow(1.0, "Spettanti Godute Residue Spettanti Godute Residue Spettanti Godute Residue"),
        Row(
            top=2.0,
            words=[w("AP2", 20)] + [w("0,00", 50 + i * 60) for i in range(9)],
        ),
        Row(
            top=3.0,
            words=[w("AP", 20)] + [w(f"{i}0,00", 50 + i * 60) for i in range(9)],
        ),
        Row(
            top=4.0,
            words=[w("AC", 20)] + [w(f"{i}0,00", 50 + i * 60) for i in range(9)],
        ),
    ]
    balances = c._extract_leave_balances(rows)
    assert len(balances) == 3
    tipi = {b.tipo for b in balances}
    assert tipi == {"ferie", "rol_ex_festivita", "banca_ore_riposi"}
    ferie = next(b for b in balances if b.tipo == "ferie")
    assert ferie.maturato == Decimal("00.00")


def test_extract_leave_balances_senza_header_restituisce_vuoto():
    assert c._extract_leave_balances([trow(1.0, "riga qualunque")]) == []


def test_extract_leave_balances_senza_riga_ac_restituisce_vuoto():
    rows = [
        trow(1.0, "Spettanti Godute Residue Spettanti Godute Residue Spettanti Godute Residue"),
        Row(top=2.0, words=[w("AP", 20), w("10,00", 50)]),
    ]
    assert c._extract_leave_balances(rows) == []


def test_extract_leave_balances_ignora_riga_vuota_e_tipo_assente():
    rows = [
        trow(1.0, "Spettanti Godute Residue Spettanti Godute Residue Spettanti Godute Residue"),
        Row(top=2.0, words=[]),
        Row(top=3.0, words=[w("AC", 20), w("10,00", 50), w("5,00", 110)]),
    ]
    balances = c._extract_leave_balances(rows)
    # solo "ferie" ha dati (maturato/goduto); gli altri due tipi restano
    # completamente vuoti e vengono scartati (v. riga "continue").
    assert len(balances) == 1
    assert balances[0].tipo == "ferie"
    assert balances[0].maturato == Decimal("10.00")


def test_extract_leave_balances_ap2_diverso_da_zero_crea_entry_separata():
    rows = [
        trow(1.0, "Spettanti Godute Residue Spettanti Godute Residue Spettanti Godute Residue"),
        # residuo_ap2 e' il 3o valore (indice 2, posizione "residuo" di "ferie"):
        # i primi due valori sono placeholder a 0 per allineare l'indice.
        Row(top=2.0, words=[w("AP2", 20), w("0,00", 50), w("0,00", 110), w("15,00", 230)]),
        Row(top=3.0, words=[w("AC", 20), w("10,00", 50), w("5,00", 110), w("2,00", 230)]),
    ]
    balances = c._extract_leave_balances(rows)
    tipi = {b.tipo for b in balances}
    assert "ferie_ap2" in tipi
    ap2 = next(b for b in balances if b.tipo == "ferie_ap2")
    assert ap2.residuo == Decimal("15.00")


# ---------------------------------------------------------------------------
# _find_iban_in_row / _extract_totals
# ---------------------------------------------------------------------------


def test_find_iban_in_row_etichette_intrecciate():
    cin_eur, cin, abi, cab, cc = _iban_parts_valido()
    row = Row(
        top=1.0,
        words=[
            w("Paese", 20),
            w("IT", 60),
            w("Cin", 90),
            w("Eur", 120),
            w(cin_eur, 150),
            w("CIN", 180),
            w(cin, 210),
            w("ABI", 240),
            w(abi, 270),
            w("CAB", 300),
            w(cab, 330),
            w("C/C", 360),
            w(cc, 390),
        ],
    )
    iban = c._find_iban_in_row(row)
    assert iban == f"IT{cin_eur}{cin}{abi}{cab}{cc}"


def test_find_iban_in_row_valori_consecutivi_senza_etichette():
    cin_eur, cin, abi, cab, cc = _iban_parts_valido()
    row = Row(top=1.0, words=[w("IT", 20), w(cin_eur, 60), w(cin, 90), w(abi, 120), w(cab, 150), w(cc, 180)])
    iban = c._find_iban_in_row(row)
    assert iban == f"IT{cin_eur}{cin}{abi}{cab}{cc}"


def test_find_iban_in_row_nessun_match():
    row = Row(top=1.0, words=[w("nessun", 20), w("iban", 60)])
    assert c._find_iban_in_row(row) is None


def test_find_iban_in_row_manca_cin():
    row = Row(top=1.0, words=[w("97", 20), w("999", 60)])
    assert c._find_iban_in_row(row) is None


def test_find_iban_in_row_manca_abi():
    row = Row(top=1.0, words=[w("97", 20), w("E", 60), w("nonabi", 90)])
    assert c._find_iban_in_row(row) is None


def test_find_iban_in_row_manca_cab():
    row = Row(top=1.0, words=[w("97", 20), w("E", 60), w("03111", 90), w("noncab", 120)])
    assert c._find_iban_in_row(row) is None


def test_find_iban_in_row_manca_cc():
    row = Row(top=1.0, words=[w("97", 20), w("E", 60), w("03111", 90), w("11706", 120), w("nonccc", 150)])
    assert c._find_iban_in_row(row) is None


def test_extract_totals_completo():
    cin_eur, cin, abi, cab, cc = _iban_parts_valido()
    rows = [
        trow(560.0, "Totale Ritenute Totale Competenze"),
        Row(top=572.0, words=[w("100,00", 440), w("2.000,00", 510)]),
        Row(
            top=594.0,
            words=[
                w("Paese", 20),
                w("IT", 60),
                w(cin_eur, 90),
                w("CIN", 120),
                w(cin, 150),
                w("ABI", 180),
                w(abi, 210),
                w("CAB", 240),
                w(cab, 270),
                w("C/C", 300),
                w(cc, 330),
                w("NETTO", 447),
                w("A", 485),
                w("PAGARE", 495),
            ],
        ),
        Row(top=605.0, words=[w("Valuta", 295), w("27/10/2016", 350)]),
        Row(top=619.0, words=[w("1.900,00", 471)]),
    ]
    totals = c._extract_totals(rows)
    assert totals.totale_trattenute == Decimal("100.00")
    assert totals.totale_competenze == Decimal("2000.00")
    assert totals.iban == f"IT{cin_eur}{cin}{abi}{cab}{cc}"
    assert totals.netto_mese == Decimal("1900.00")


def test_extract_totals_iban_su_riga_precedente():
    # v. _find_iban_in_row: su alcuni Win2PDF etichette e valori IBAN finiscono
    # sulla riga immediatamente precedente a "NETTO A PAGARE".
    cin_eur, cin, abi, cab, cc = _iban_parts_valido()
    rows = [
        Row(top=1.0, words=[w("IT", 20), w(cin_eur, 60), w(cin, 90), w(abi, 120), w(cab, 150), w(cc, 180)]),
        trow(2.0, "NETTO A PAGARE"),
        Row(top=3.0, words=[w("1.000,00", 100)]),
    ]
    totals = c._extract_totals(rows)
    assert totals.iban == f"IT{cin_eur}{cin}{abi}{cab}{cc}"
    assert totals.netto_mese == Decimal("1000.00")


def test_extract_totals_senza_dati_resta_none():
    totals = c._extract_totals([trow(1.0, "riga qualunque")])
    assert totals.totale_trattenute is None
    assert totals.iban is None
    assert totals.netto_mese is None


def test_extract_totals_un_solo_valore_va_a_competenze():
    rows = [
        trow(560.0, "Totale Ritenute Totale Competenze"),
        Row(top=572.0, words=[w("2.000,00", 510)]),
    ]
    totals = c._extract_totals(rows)
    assert totals.totale_trattenute is None
    assert totals.totale_competenze == Decimal("2000.00")


# ---------------------------------------------------------------------------
# map_document (end-to-end)
# ---------------------------------------------------------------------------


def _happy_path_rows() -> list[Row]:
    cin_eur, cin, abi, cab, cc = _iban_parts_valido()
    return [
        trow(20.0, "Codice Azienda/Filiale/Stabil Ragione Sociale Azienda"),
        trow(34.0, "ATS/ 01/ VR ACCENTURE TECHNOLOGY SOLUTIONS SRL"),
        trow(60.0, "7516/80007516 ROSSI MARIO"),
        trow(107.0, f"37124 VERONA 13600/22274764-04 04/07/2016 23/04/1991 {CF_VALIDO} del"),
        trow(148.0, "Ottobre2016"),
        trow(255.0, "Cod. Descrizione Ore/GG % Dato Base Ritenute Competenze"),
        Row(top=264.0, words=[w("0001", 20), w("RETRIBUZIONE", 55), w("1.500,00", 529)]),
        trow(325.0, "Totale Ritenute Sociali"),
        trow(560.0, "Totale Ritenute Totale Competenze"),
        Row(top=572.0, words=[w("100,00", 440), w("1.500,00", 510)]),
        Row(
            top=594.0,
            words=[
                w("Paese", 20),
                w("IT", 60),
                w(cin_eur, 90),
                w("CIN", 120),
                w(cin, 150),
                w("ABI", 180),
                w(abi, 210),
                w("CAB", 240),
                w(cab, 270),
                w("C/C", 300),
                w(cc, 330),
                w("NETTO", 447),
                w("A", 485),
                w("PAGARE", 495),
            ],
        ),
        Row(top=619.0, words=[w("1.400,00", 471)]),
    ]


def test_map_document_happy_path_senza_anomalie():
    doc = _doc(_happy_path_rows())
    dto = c.map_document(doc)
    assert dto.template_name == "copernico_paghe"
    assert dto.company.ragione_sociale == "ACCENTURE TECHNOLOGY SOLUTIONS SRL"
    assert dto.employee.codice_fiscale == CF_VALIDO
    assert dto.period.mese == 10
    assert dto.period.anno == 2016
    assert dto.totals.netto_mese == Decimal("1400.00")
    assert len(dto.pay_lines) == 1
    assert dto.anomalies == []


def test_map_document_cf_checksum_non_valido():
    rows = _happy_path_rows()
    rows[3] = trow(107.0, f"37124 VERONA 13600/22274764-04 04/07/2016 23/04/1991 {CF_CHECKSUM_ERRATO} del")
    doc = _doc(rows)
    dto = c.map_document(doc)
    assert dto.employee.codice_fiscale == ""
    assert any(a.tipo == "codice_fiscale_non_valido" for a in dto.anomalies)


def test_map_document_ragione_sociale_mancante():
    rows = [r for r in _happy_path_rows() if "ATS/" not in r.text]
    doc = _doc(rows)
    dto = c.map_document(doc)
    assert dto.company.ragione_sociale == ""
    assert any(a.tipo == "header_incompleto" and a.campo == "company.ragione_sociale" for a in dto.anomalies)


def test_map_document_periodo_non_riconosciuto():
    rows = [r for r in _happy_path_rows() if r.text != "Ottobre2016"]
    doc = _doc(rows)
    dto = c.map_document(doc)
    assert dto.period.mese == 0
    assert any(a.tipo == "periodo_non_riconosciuto" for a in dto.anomalies)


def test_map_document_righe_non_mappate():
    rows = _happy_path_rows() + []
    # Inserisce una riga di boilerplate senza codice tra header e fine sezione.
    idx = rows.index(next(r for r in rows if r.text == "Totale Ritenute Sociali"))
    rows.insert(idx, trow(300.0, "Imponibile Previdenziale Non Arrotondato"))
    doc = _doc(rows)
    dto = c.map_document(doc)
    assert any(a.tipo == "righe_non_mappate" for a in dto.anomalies)


def test_map_document_testo_ricostruito():
    doc = _doc(_happy_path_rows())
    doc.pages[0].recovered_from_scramble = True
    dto = c.map_document(doc)
    assert any(a.tipo == "testo_ricostruito" for a in dto.anomalies)


def test_map_document_totali_mancanti_forza_error():
    rows = [r for r in _happy_path_rows() if "NETTO" not in r.text and r.top not in (594.0, 619.0)]
    doc = _doc(rows)
    dto = c.map_document(doc)
    assert any(a.tipo == "totali_mancanti" and a.severita.value == "error" for a in dto.anomalies)


def test_map_document_iban_non_valido():
    rows = _happy_path_rows()
    for i, row in enumerate(rows):
        if row.top == 594.0:
            # Ricompone lo stesso IBAN ma con un CIN/EUR palesemente errato,
            # cosi' che il checksum mod-97 fallisca.
            rows[i] = Row(
                top=594.0,
                words=[
                    w("Paese", 20),
                    w("IT", 60),
                    w("01", 90),
                    w("CIN", 120),
                    w("E", 150),
                    w("ABI", 180),
                    w("03111", 210),
                    w("CAB", 240),
                    w("11706", 270),
                    w("C/C", 300),
                    w("000000012863", 330),
                    w("NETTO", 447),
                    w("A", 485),
                    w("PAGARE", 495),
                ],
            )
    doc = _doc(rows)
    dto = c.map_document(doc)
    assert any(a.tipo == "iban_non_valido" for a in dto.anomalies)


def test_map_document_multipagina_concatena_pay_lines():
    pagina1 = [
        trow(20.0, "Codice Azienda/Filiale/Stabil Ragione Sociale Azienda"),
        trow(34.0, "ATS/ 01/ VR ACCENTURE TECHNOLOGY SOLUTIONS SRL"),
        trow(255.0, "Cod. Descrizione Ore/GG % Dato Base Ritenute Competenze"),
        Row(top=264.0, words=[w("0001", 20), w("RETRIBUZIONE", 55), w("1.500,00", 529)]),
    ]
    pagina2 = [
        trow(255.0, "Cod. Descrizione Ore/GG % Dato Base Ritenute Competenze"),
        Row(top=264.0, words=[w("0002", 20), w("STRAORDINARIO", 55), w("200,00", 529)]),
        trow(325.0, "Totale Ritenute Sociali"),
    ]
    doc = _doc(pagina1, extra_pages=[pagina2])
    dto = c.map_document(doc)
    assert {line.codice for line in dto.pay_lines} == {"0001", "0002"}
