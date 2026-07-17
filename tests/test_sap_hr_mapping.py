"""Suite di copertura per il template SAP HR (packages/payroll-ingest/src/
payroll_ingest/templates/sap_hr.py). Nessun PDF reale: Row/Word sintetici come
nel resto della suite (i campioni reali sono gitignored, dati personali),
stesso stile di test_zucchetti_mapping.py/test_copernico_mapping.py."""

from decimal import Decimal
from pathlib import Path

from payroll_ingest.dto import PeriodType
from payroll_ingest.extraction import RawExtractedDocument, RawPage, Row, Word
from payroll_ingest.templates import sap_hr as s
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


def _page(rows: list[Row], words: list[Word] | None = None) -> RawPage:
    page_words = words if words is not None else [word for row in rows for word in row.words]
    return RawPage(words=page_words, rows=rows, full_text="", width=600.0, height=800.0)


def _doc(rows: list[Row]) -> RawExtractedDocument:
    return RawExtractedDocument(source_path=Path("sintetico.pdf"), pages=[_page(rows)])


def _iban_valido() -> str:
    # ABI(5) + CAB(5) + C/C(12) = 22 cifre esatte dopo la lettera CIN, per un
    # totale di 27 caratteri IBAN standard.
    abi, cab, cc_num, cin = "03111", "11706", "000000012863", "E"
    for cin_eur in range(100):
        candidate = f"IT{cin_eur:02d}{cin}{abi}{cab}{cc_num}"
        if iban_mod97_valid(candidate):
            return candidate
    raise AssertionError("nessun IBAN sintetico checksum-valido trovato")


CF_VALIDO = "RSSMRA80A01H501U"
CF_CHECKSUM_ERRATO = "RSSMRA80A01H501A"


# ---------------------------------------------------------------------------
# is_sap_hr_document
# ---------------------------------------------------------------------------


def test_is_sap_hr_document_riconosciuto():
    rows = [
        trow(206.0, "SAP Nr.: 12345678"),
        trow(302.0, "VOCI RETRIBUTIVE ORE/GIORNI IMPORTO UNITARIO"),
    ]
    assert s.is_sap_hr_document(_doc(rows)) is True


def test_is_sap_hr_document_manca_sap_nr():
    rows = [trow(302.0, "VOCI RETRIBUTIVE ORE/GIORNI IMPORTO UNITARIO")]
    assert s.is_sap_hr_document(_doc(rows)) is False


def test_is_sap_hr_document_manca_voci_retributive():
    rows = [trow(206.0, "SAP Nr.: 12345678")]
    assert s.is_sap_hr_document(_doc(rows)) is False


def test_is_sap_hr_document_sap_fuori_dall_header():
    rows = [
        trow(500.0, "SAP Nr.: 12345678"),
        trow(302.0, "VOCI RETRIBUTIVE ORE/GIORNI IMPORTO UNITARIO"),
    ]
    assert s.is_sap_hr_document(_doc(rows)) is False


# ---------------------------------------------------------------------------
# _parse_ragione_sociale / _parse_matricola_codice / _parse_codice_fiscale /
# _parse_hire_date_str / _parse_header
# ---------------------------------------------------------------------------


def test_parse_ragione_sociale_ancorata_dopo_libro_unico():
    rows = [
        trow(81.0, "LIBRO UNICO DEL LAVORO Progressivo: 4"),
        trow(90.0, "ACCENTURE TECHNOLOGY SOLUTIONS SRL 20100 MILANO"),
    ]
    assert s._parse_ragione_sociale(rows) == "ACCENTURE TECHNOLOGY SOLUTIONS SRL"


def test_parse_ragione_sociale_rinominata_2020():
    rows = [
        trow(81.0, "LIBRO UNICO DEL LAVORO"),
        trow(90.0, "ACCENTURE FINANCIAL ADVANCED SOLUTIONS & TECHNOLOGY S.R.L. 20100"),
    ]
    assert s._parse_ragione_sociale(rows) == "ACCENTURE FINANCIAL ADVANCED SOLUTIONS & TECHNOLOGY S.R.L."


def test_parse_ragione_sociale_senza_ancora():
    assert s._parse_ragione_sociale([trow(1.0, "riga qualunque")]) == ""


def test_parse_ragione_sociale_ancora_ultima_riga():
    assert s._parse_ragione_sociale([trow(81.0, "LIBRO UNICO DEL LAVORO")]) == ""


def test_parse_matricola_codice():
    rows = [trow(196.0, "Codice: 1740"), trow(206.0, "SAP Nr.: 12345678")]
    matricola, codice_azienda = s._parse_matricola_codice(rows)
    assert matricola == "12345678"
    assert codice_azienda == "1740"


def test_parse_matricola_codice_assenti():
    matricola, codice_azienda = s._parse_matricola_codice([trow(1.0, "riga qualunque")])
    assert matricola is None
    assert codice_azienda is None


def test_parse_codice_fiscale_ignora_cf_azienda():
    rows = [
        trow(146.0, "12345678901"),  # CF azienda a 11 cifre: non deve matchare
        trow(129.0, CF_VALIDO),
    ]
    assert s._parse_codice_fiscale(rows) == CF_VALIDO


def test_parse_codice_fiscale_assente():
    assert s._parse_codice_fiscale([trow(1.0, "nessun cf qui")]) == ""


def test_parse_hire_date_str_prende_la_data_piu_a_destra():
    rows = [
        trow(109.0, "Data Ass. Conv. Data Assunzione"),
        trow(113.0, "01/01/2015 04/07/2016"),
    ]
    assert s._parse_hire_date_str(rows) == "04/07/2016"


def test_parse_hire_date_str_assente():
    assert s._parse_hire_date_str([trow(1.0, "riga qualunque")]) is None


def test_parse_header_estrae_tutti_i_campi():
    rows = [
        trow(81.0, "LIBRO UNICO DEL LAVORO"),
        trow(90.0, "ACCENTURE TECHNOLOGY SOLUTIONS SRL"),
        trow(109.0, "Data Ass. Conv. Data Assunzione"),
        trow(113.0, "01/01/2015 04/07/2016"),
        trow(129.0, CF_VALIDO),
        trow(196.0, "Codice: 1740"),
        trow(206.0, "SAP Nr.: 12345678"),
    ]
    company, employee, hire_date_str = s._parse_header(rows)
    assert company.ragione_sociale == "ACCENTURE TECHNOLOGY SOLUTIONS SRL"
    assert company.codice_azienda == "1740"
    assert employee.matricola == "12345678"
    assert employee.codice_fiscale == CF_VALIDO
    assert hire_date_str == "04/07/2016"


# ---------------------------------------------------------------------------
# _parse_date_slash / _parse_period
# ---------------------------------------------------------------------------


def test_parse_date_slash_valida_e_non_valida():
    d = s._parse_date_slash("4/7/2016")
    assert d is not None and (d.year, d.month, d.day) == (2016, 7, 4)
    assert s._parse_date_slash("31/11/2020") is None
    assert s._parse_date_slash("non una data") is None


def test_parse_period_ordinario():
    tipo, mese, anno, label = s._parse_period([trow(259.7, "Febbraio 2019")])
    assert tipo == PeriodType.ORDINARIO
    assert (mese, anno) == (2, 2019)
    assert label == "Febbraio 2019"


def test_parse_period_tredicesima():
    tipo, mese, anno, _label = s._parse_period([trow(272.1, "Dicembre 2020 Tredicesima")])
    assert tipo == PeriodType.MENSILITA_AGGIUNTIVA
    assert (mese, anno) == (12, 2020)


def test_parse_period_non_riconosciuto():
    tipo, mese, anno, label = s._parse_period([trow(1.0, "testo qualunque")])
    assert tipo == PeriodType.ORDINARIO
    assert (mese, anno) == (0, 0)
    assert label == ""


# ---------------------------------------------------------------------------
# _column_of / _parse_pay_line_row
# ---------------------------------------------------------------------------


def test_column_of_sezione1():
    assert s._column_of(s.COMPETENZE_MIN, s._SECTION1_ZONES) == "competenza"
    assert s._column_of(s.TRATTENUTE_MIN, s._SECTION1_ZONES) == "trattenuta"
    assert s._column_of(s.IMPORTI_FIGURATI_MIN, s._SECTION1_ZONES) == "importi_figurati"
    assert s._column_of(s.IMPORTO_UNITARIO_MIN, s._SECTION1_ZONES) == "importo_base"
    assert s._column_of(s.ORE_GIORNI_MIN, s._SECTION1_ZONES) == "ore_giorni"
    assert s._column_of(0.0, s._SECTION1_ZONES) is None


def test_parse_pay_line_row_sezione1():
    row = Row(
        top=310.0,
        words=[w("AA245", 21), w("Retribuzione", 58), w("10,00", 248), w("100,00", 305), w("1.000,00", 536)],
    )
    line = s._parse_pay_line_row(row, s._SECTION1_ZONES)
    assert line is not None
    assert line.codice == "AA245"
    assert line.quantita == Decimal("10.00")
    assert line.importo_base == Decimal("100.00")
    assert line.competenza == Decimal("1000.00")


def test_parse_pay_line_row_flag_figurativo():
    row = Row(top=310.0, words=[w("W1100", 21), w("Vers.TFR", 58), w("50,00", 370)])
    line = s._parse_pay_line_row(row, s._SECTION1_ZONES)
    assert line is not None
    assert line.note == "valore esclusivamente figurativo (non concorre al netto)"
    assert line.importo_base is None


def test_parse_pay_line_row_sezione2():
    row = Row(top=408.0, words=[w("005", 21), w("INPS", 58), w("2.000,00", 312), w("9,19", 403), w("50,00", 480)])
    line = s._parse_pay_line_row(row, s._SECTION2_ZONES)
    assert line is not None
    assert line.importo_base == Decimal("2000.00")
    assert line.aliquota == Decimal("9.19")
    assert line.trattenuta == Decimal("50.00")


def test_parse_pay_line_row_senza_codice_valido():
    assert s._parse_pay_line_row(Row(top=1.0, words=[w("F.do", 21), w("Sostit.", 58)]), s._SECTION1_ZONES) is None


def test_parse_pay_line_row_senza_descrizione():
    row = Row(top=1.0, words=[w("005", 21), w("100,00", 300)])
    assert s._parse_pay_line_row(row, s._SECTION2_ZONES) is None


def test_parse_pay_line_row_descrizione_con_token_unita_non_troncata():
    row = Row(
        top=310.0,
        words=[w("0282", 21), w("ORE", 58), w("STRAORD.60%", 95), w("MESE", 165), w("PRECEDENTE", 198), w("8,00", 248)],
    )
    line = s._parse_pay_line_row(row, s._SECTION1_ZONES)
    assert line is not None
    assert line.descrizione == "ORE STRAORD.60% MESE PRECEDENTE"
    assert line.quantita == Decimal("8.00")


def test_parse_pay_line_row_descrizione_banca_ore_senza_troncamento():
    row = Row(top=310.0, words=[w("0299", 21), w("BANCA", 58), w("ORE", 110), w("GODUTE", 145), w("1,00", 248)])
    line = s._parse_pay_line_row(row, s._SECTION1_ZONES)
    assert line is not None
    assert line.descrizione == "BANCA ORE GODUTE"
    assert line.quantita == Decimal("1.00")


def test_parse_pay_line_row_ignora_marker_parentesi_e_token_non_numerico():
    row = Row(
        top=1.0,
        words=[w("005", 21), w("INPS", 58), w("(", 300), w("N/A", 310), w("50,00", 480)],
    )
    line = s._parse_pay_line_row(row, s._SECTION2_ZONES)
    assert line is not None
    assert line.trattenuta == Decimal("50.00")


# ---------------------------------------------------------------------------
# _extract_pay_lines_from_page
# ---------------------------------------------------------------------------


def test_extract_pay_lines_from_page_due_sezioni():
    rows = [
        trow(302.0, "VOCI RETRIBUTIVE ORE/GIORNI IMPORTO UNITARIO"),
        Row(top=310.0, words=[w("AA245", 21), w("Retribuzione", 58), w("1.000,00", 536)]),
        trow(400.0, "TRATTENUTE PREVIDENZIALI IMPONIBILI ALIQUOTE"),
        Row(top=408.0, words=[w("005", 21), w("INPS", 58), w("50,00", 480)]),
        trow(429.0, "CTB. DED. CTB.NON DED."),
        trow(449.0, "ADDIZIONALI ANNO IMPON/RATA"),
        Row(top=457.0, words=[w("001", 21), w("Addizionale", 58), w("regionale", 100), w("30,00", 480)]),
    ]
    pay_lines, unmapped = s._extract_pay_lines_from_page(rows)
    assert {line.codice for line in pay_lines} == {"AA245", "005"}
    assert unmapped == ["CTB. DED. CTB.NON DED."]


def test_extract_pay_lines_from_page_senza_header_restituisce_vuoto():
    pay_lines, unmapped = s._extract_pay_lines_from_page([trow(1.0, "riga qualunque")])
    assert pay_lines == []
    assert unmapped == []


# ---------------------------------------------------------------------------
# _extract_imponibile_irpef / _build_detrazioni_markers / _extract_tax
# ---------------------------------------------------------------------------


def test_extract_imponibile_irpef():
    rows = [trow(592.0, "Emolumenti correnti 2.500,00 3.000,00")]
    assert s._extract_imponibile_irpef(rows) == Decimal("2500.00")


def test_extract_imponibile_irpef_assente():
    assert s._extract_imponibile_irpef([trow(1.0, "riga qualunque")]) is None


def test_build_detrazioni_markers_disambigua_lorda_netta_lavdip():
    row = Row(
        top=685.0,
        words=[
            w("Imposta", 30),
            w("Lorda", 57),
            w("Detr.", 92),
            w("Lav.", 109),
            w("Dip.", 124),
            w("Detr.", 155),
            w("Coniuge", 172),
            w("Imposta", 515),
            w("Netta", 542),
        ],
    )
    markers = s._build_detrazioni_markers(row)
    assert dict((f, x0) for x0, f in markers) == {"irpef_lorda": 30, "detrazioni_lav_dip": 92, "ritenute_irpef": 515}


def test_extract_tax_box_detrazioni_e_addizionali():
    rows = [
        trow(592.0, "Emolumenti correnti 2.500,00"),
        Row(
            top=685.0,
            words=[
                w("Imposta", 30),
                w("Lorda", 57),
                w("Detr.", 92),
                w("Lav.", 109),
                w("Dip.", 124),
                w("Imposta", 515),
                w("Netta", 542),
            ],
        ),
        Row(top=690.0, words=[w("400,00", 40), w("60,00", 100), w("250,00", 520)]),
        trow(449.0, "ADDIZIONALI ANNO IMPON/RATA"),
        Row(top=450.0, words=[]),
        Row(top=457.0, words=[w("001", 21), w("Addizionale", 58), w("regionale", 100), w("30,00", 480)]),
        trow(467.0, "VENETO"),
        Row(top=477.0, words=[w("002", 21), w("Addizionale", 58), w("comunale", 100), w("20,00", 480)]),
        trow(487.0, "VERONA"),
        Row(top=490.0, words=[w("003", 21), w("Altra", 58), w("voce", 100), w("5,00", 480)]),
        trow(588.0, "Descrizione Imponibile Fiscale Imponibili Lordo"),
    ]
    tax = s._extract_tax(rows)
    assert tax.imponibile_irpef == Decimal("2500.00")
    assert tax.irpef_lorda == Decimal("400.00")
    assert tax.detrazioni_lav_dip == Decimal("60.00")
    assert tax.ritenute_irpef == Decimal("250.00")
    assert tax.addizionale_regionale == Decimal("30.00")
    assert tax.addizionale_regionale_regione == "VENETO"
    assert tax.addizionale_comunale == Decimal("20.00")


def test_extract_tax_senza_dati_resta_none():
    tax = s._extract_tax([trow(1.0, "riga qualunque")])
    assert tax.imponibile_irpef is None
    assert tax.addizionale_regionale is None


# ---------------------------------------------------------------------------
# _extract_annual_summary (riepilogo annuale tredicesima, issue #31)
# ---------------------------------------------------------------------------


def test_extract_annual_summary_tax_e_tfr():
    rows = [
        Row(
            top=708.0,
            words=[
                w("Retr.", 29.2),
                w("Utile", 46.3),
                w("TFR", 62.2),
                w("Imponibile", 214.7),
                w("Fiscale", 248.5),
                w("Annuo", 272.6),
                w("Imposta", 304.3),
                w("Lorda", 331.1),
                w("Imposta", 443.9),
                w("Dovuta", 470.7),
                w("Imposta", 512.6),
                w("Pagata", 539.4),
            ],
        ),
        Row(
            top=714.2,
            words=[w("2.630,54", 48.9), w("33.342,23", 231.3), w("8.991,81", 322.0), w("8.391,14", 537.4)],
        ),
        Row(
            top=727.4,
            words=[
                w("Imp.", 26.0),
                w("INPS", 41.6),
                w("Progr.", 59.9),
                w("Ctr.", 88.9),
                w("INPS", 102.1),
                w("Progr.", 120.3),
                w("Ctr.", 153.6),
                w("Dip.", 166.8),
                w("INPS", 181.2),
                w("Cong.", 211.6),
                w("Credito", 232.2),
                w("Cong.", 261.6),
                w("Debito", 282.2),
            ],
        ),
        Row(top=734.8, words=[w("36.838,00", 42.9), w("3.495,91", 110.9), w("249,68", 178.9)]),
    ]
    tax_values, tfr_values = s._extract_annual_summary(rows)
    assert tax_values == {
        "imponibile_fiscale_annuo": Decimal("33342.23"),
        "imposta_lorda_annua": Decimal("8991.81"),
        "imposta_pagata_annua": Decimal("8391.14"),
        "imp_inps_progr_annuo": Decimal("36838.00"),
        "ctr_inps_progr_annuo": Decimal("3495.91"),
        "ctr_dip_inps_progr_annuo": Decimal("249.68"),
    }
    assert tfr_values == {"retribuzione_utile_tfr_annua": Decimal("2630.54")}


def test_extract_annual_summary_senza_dati_resta_vuoto():
    tax_values, tfr_values = s._extract_annual_summary([trow(1.0, "riga qualunque")])
    assert tax_values == {}
    assert tfr_values == {}


def test_extract_annual_summary_ignora_token_non_numerico_nella_riga_valori():
    rows = [
        Row(top=708.0, words=[w("Imponibile", 214.7), w("Fiscale", 248.5), w("Annuo", 272.6)]),
        Row(top=714.2, words=[w("n/d", 231.3)]),
    ]
    tax_values, tfr_values = s._extract_annual_summary(rows)
    assert tax_values == {}
    assert tfr_values == {}


def test_extract_annual_summary_etichetta_ultima_riga_non_crasha():
    # v. issue #31: sui 2 campioni reali il documento finisce subito dopo
    # l'etichetta ferie, senza righe dati - stesso rischio qui se l'etichetta
    # annuale fosse l'ultima riga del documento (nessun IndexError).
    rows = [Row(top=708.0, words=[w("Imponibile", 214.7), w("Fiscale", 248.5), w("Annuo", 272.6)])]
    tax_values, tfr_values = s._extract_annual_summary(rows)
    assert tax_values == {}
    assert tfr_values == {}


# ---------------------------------------------------------------------------
# _extract_tfr
# ---------------------------------------------------------------------------


def test_extract_tfr_entrambi_i_blocchi():
    rows = [
        Row(top=655.0, words=[w("Accant.TFR", 167), w("Anticipazioni", 304), w("Tesoreria", 366)]),
        Row(top=665.0, words=[w("200,00", 175), w("50,00", 310), w("370,00", 370)]),
        Row(top=708.0, words=[w("Retr.", 29), w("Utile", 46), w("TFR", 62)]),
        Row(top=714.0, words=[w("900,00", 48)]),
    ]
    tfr = s._extract_tfr(rows)
    assert tfr.quota_anno == Decimal("200.00")
    assert tfr.anticipi == Decimal("50.00")
    assert tfr.quota_tfr_fondi == Decimal("370.00")
    assert tfr.retribuzione_utile_tfr == Decimal("900.00")


def test_extract_tfr_senza_dati_resta_none():
    tfr = s._extract_tfr([trow(1.0, "riga qualunque")])
    assert tfr.quota_anno is None
    assert tfr.retribuzione_utile_tfr is None


# ---------------------------------------------------------------------------
# _build_leave_markers / _extract_leave_balances
# ---------------------------------------------------------------------------


def test_build_leave_markers_tutte_le_colonne():
    row = Row(
        top=750.0,
        words=[
            w("Maturate", 144),
            w("Godute", 222),
            w("Residue", 290),
            w("AP", 318),
            w("Residue", 365),
            w("AP2", 393),
            w("Saldo", 452),
        ],
    )
    markers = dict((f, x0) for x0, f in s._build_leave_markers(row))
    assert markers == {"maturato": 144, "goduto": 222, "residuo_ap": 290, "residuo_ap2": 365, "residuo": 452}


def test_extract_leave_balances_righe_sparse():
    header = Row(
        top=750.0,
        words=[
            w("Maturate", 144, top=750.0),
            w("Godute", 222, top=750.0),
            w("Residue", 290, top=750.0),
            w("AP", 318, top=750.0),
            w("Residue", 365, top=750.0),
            w("AP2", 393, top=750.0),
            w("Saldo", 452, top=750.0),
        ],
    )
    rows = [
        header,
        Row(top=757.0, words=[w("FERIE", 20), w("100,00", 140), w("50,00", 226), w("10,00", 300), w("30,00", 447)]),
        Row(top=767.0, words=[w("R.O.L.", 20), w("20,00", 226), w("5,00", 300), w("15,00", 447)]),
        Row(top=776.0, words=[w("B.ORE", 20)]),
    ]
    balances = s._extract_leave_balances(rows)
    tipi = {b.tipo for b in balances}
    assert "ferie" in tipi and "rol_ex_festivita" in tipi
    ferie = next(b for b in balances if b.tipo == "ferie")
    assert ferie.maturato == Decimal("100.00")
    assert ferie.residuo == Decimal("30.00")
    rol = next(b for b in balances if b.tipo == "rol_ex_festivita")
    assert rol.maturato is None
    assert rol.goduto == Decimal("20.00")


def test_extract_leave_balances_senza_header_restituisce_vuoto():
    assert s._extract_leave_balances([trow(1.0, "riga qualunque")]) == []


def test_extract_leave_balances_header_senza_marker_restituisce_vuoto():
    # La riga soddisfa il check di rilevamento header (normalize_label
    # contiene tutte e 4 le etichette) ma e' un unico token fuso: nessuna
    # parola combacia esattamente con "maturate"/"godute"/... e
    # _build_leave_markers non produce alcun marker.
    header = Row(top=750.0, words=[w("MaturateGoduteResidueAPResidueAP2Saldo", 20)])
    assert s._extract_leave_balances([header]) == []


def test_extract_leave_balances_ignora_riga_vuota_e_tipo_non_riconosciuto():
    header = Row(
        top=750.0,
        words=[
            w("Maturate", 144, top=750.0),
            w("Godute", 222, top=750.0),
            w("Residue", 290, top=750.0),
            w("AP", 318, top=750.0),
            w("Residue", 365, top=750.0),
            w("AP2", 393, top=750.0),
            w("Saldo", 452, top=750.0),
        ],
    )
    rows = [
        header,
        Row(top=751.0, words=[]),
        Row(top=752.0, words=[w("ALTRO", 20), w("10,00", 144)]),
        Row(top=757.0, words=[w("FERIE", 20), w("100,00", 144), w("50,00", 222)]),
    ]
    balances = s._extract_leave_balances(rows)
    assert len(balances) == 1
    assert balances[0].tipo == "ferie"


def test_extract_leave_balances_ap2_diverso_da_zero():
    header = Row(
        top=750.0,
        words=[
            w("Maturate", 144, top=750.0),
            w("Godute", 222, top=750.0),
            w("Residue", 290, top=750.0),
            w("AP", 318, top=750.0),
            w("Residue", 365, top=750.0),
            w("AP2", 393, top=750.0),
            w("Saldo", 452, top=750.0),
        ],
    )
    rows = [
        header,
        Row(
            top=757.0,
            words=[
                w("FERIE", 20),
                w("100,00", 140),
                w("50,00", 226),
                w("10,00", 300),
                w("5,00", 365),
                w("30,00", 447),
            ],
        ),
    ]
    balances = s._extract_leave_balances(rows)
    assert any(b.tipo == "ferie_ap2" and b.residuo == Decimal("5.00") for b in balances)


# ---------------------------------------------------------------------------
# _amount_below_label / _extract_totals
# ---------------------------------------------------------------------------


def test_amount_below_label_trova_il_valore_fuori_riga():
    words = [w("NETTO", 484, top=641.6), w("200,00", 30, top=665.7), w("1.900,00", 493, top=665.7)]
    amount = s._amount_below_label(words, label_x0=484, label_top=641.6, x_pad=30.0, max_dy=35.0)
    assert amount == Decimal("1900.00")


def test_amount_below_label_fuori_finestra_dy():
    words = [w("100,00", 484, top=700.0)]
    assert s._amount_below_label(words, label_x0=484, label_top=641.6, x_pad=30.0, max_dy=35.0) is None


def test_extract_totals_completo():
    iban = _iban_valido()
    rows = [
        trow(588.0, "Totale Trattenute Totale Competenze"),
        Row(top=617.0, words=[w("100,00", 468, top=617.0), w("2.000,00", 538, top=617.0)]),
        Row(top=641.0, words=[w("NETTO", 484, top=641.0)]),
        Row(top=665.0, words=[w("200,00", 30, top=665.0), w("1.900,00", 493, top=665.0)]),
        Row(top=633.0, words=[w(iban, 56, top=633.0)]),
    ]
    page_words = [word for row in rows for word in row.words]
    totals = s._extract_totals(rows, page_words)
    assert totals.totale_trattenute == Decimal("100.00")
    assert totals.totale_competenze == Decimal("2000.00")
    assert totals.iban == iban
    assert totals.netto_mese == Decimal("1900.00")


def test_extract_totals_ignora_riga_emolumenti_correnti_prima_del_vero_totale():
    # Issue #42: la riga "Emolumenti correnti" (Imponibile Fiscale/Imponibili
    # Lordo, entrambi x0<COMPETENZE_MIN ma NON trattenute) precede sempre il
    # vero totale su ogni cedolino SAP HR - senza soglia inferiore su
    # trattenute_vals, questa riga veniva scambiata per il totale e il loop
    # si fermava prima di raggiungere quella vera (totale_competenze restava
    # sempre None, totale_trattenute sempre sbagliato, su 25/25 file reali).
    rows = [
        trow(588.0, "Totale Trattenute Totale Competenze"),
        Row(top=592.0, words=[w("2.610,56", 295, top=592.0), w("685,35", 402, top=592.0)]),
        Row(top=617.0, words=[w("1.141,66", 468, top=617.0), w("2.884,25", 538, top=617.0)]),
    ]
    totals = s._extract_totals(rows, [word for row in rows for word in row.words])
    assert totals.totale_trattenute == Decimal("1141.66")
    assert totals.totale_competenze == Decimal("2884.25")


def test_extract_totals_senza_dati_resta_none():
    rows = [trow(1.0, "riga qualunque")]
    totals = s._extract_totals(rows, [word for row in rows for word in row.words])
    assert totals.totale_trattenute is None
    assert totals.iban is None
    assert totals.netto_mese is None


# ---------------------------------------------------------------------------
# map_document (end-to-end)
# ---------------------------------------------------------------------------


def _happy_path_rows() -> list[Row]:
    iban = _iban_valido()
    return [
        trow(81.0, "LIBRO UNICO DEL LAVORO"),
        trow(90.0, "ACCENTURE TECHNOLOGY SOLUTIONS SRL"),
        trow(109.0, "Data Ass. Conv. Data Assunzione"),
        trow(113.0, "01/01/2015 04/07/2016"),
        trow(129.0, CF_VALIDO),
        trow(196.0, "Codice: 1740"),
        trow(206.0, "SAP Nr.: 12345678"),
        trow(259.7, "Febbraio 2019"),
        trow(302.0, "VOCI RETRIBUTIVE ORE/GIORNI IMPORTO UNITARIO"),
        Row(top=310.0, words=[w("AA245", 21), w("Retribuzione", 58), w("1.000,00", 536)]),
        trow(400.0, "TRATTENUTE PREVIDENZIALI IMPONIBILI ALIQUOTE"),
        trow(449.0, "ADDIZIONALI ANNO IMPON/RATA"),
        trow(588.0, "Totale Trattenute Totale Competenze"),
        Row(top=617.0, words=[w("100,00", 468, top=617.0), w("1.000,00", 538, top=617.0)]),
        Row(top=633.0, words=[w(iban, 56, top=633.0)]),
        Row(top=641.0, words=[w("NETTO", 484, top=641.0)]),
        Row(top=665.0, words=[w("200,00", 30, top=665.0), w("900,00", 493, top=665.0)]),
    ]


def test_map_document_happy_path_senza_anomalie():
    doc = _doc(_happy_path_rows())
    dto = s.map_document(doc)
    assert dto.template_name == "sap_hr"
    assert dto.company.ragione_sociale == "ACCENTURE TECHNOLOGY SOLUTIONS SRL"
    assert dto.employee.codice_fiscale == CF_VALIDO
    assert dto.period.mese == 2
    assert dto.period.anno == 2019
    assert dto.totals.netto_mese == Decimal("900.00")
    assert len(dto.pay_lines) == 1
    assert dto.anomalies == []


def test_map_document_cf_checksum_non_valido():
    rows = [r if r.text != CF_VALIDO else trow(129.0, CF_CHECKSUM_ERRATO) for r in _happy_path_rows()]
    doc = _doc(rows)
    dto = s.map_document(doc)
    assert dto.employee.codice_fiscale == ""
    assert any(a.tipo == "codice_fiscale_non_valido" for a in dto.anomalies)


def test_map_document_cf_assente():
    rows = [r for r in _happy_path_rows() if r.text != CF_VALIDO]
    doc = _doc(rows)
    dto = s.map_document(doc)
    assert any(a.tipo == "header_incompleto" and a.campo == "employee.codice_fiscale" for a in dto.anomalies)


def test_map_document_testo_ricostruito():
    doc = _doc(_happy_path_rows())
    doc.pages[0].recovered_from_scramble = True
    dto = s.map_document(doc)
    assert any(a.tipo == "testo_ricostruito" for a in dto.anomalies)


def test_map_document_ragione_sociale_mancante():
    rows = [r for r in _happy_path_rows() if "ACCENTURE" not in r.text]
    doc = _doc(rows)
    dto = s.map_document(doc)
    assert dto.company.ragione_sociale == ""
    assert any(a.tipo == "header_incompleto" and a.campo == "company.ragione_sociale" for a in dto.anomalies)


def test_map_document_periodo_non_riconosciuto():
    rows = [r for r in _happy_path_rows() if r.text != "Febbraio 2019"]
    doc = _doc(rows)
    dto = s.map_document(doc)
    assert dto.period.mese == 0
    assert any(a.tipo == "periodo_non_riconosciuto" for a in dto.anomalies)


def test_map_document_righe_non_mappate_puro_rumore_non_genera_anomalia():
    # "CTB. DED. CTB.NON DED." - fragment di intestazione colonna presente
    # identico su 23/23 file SAP HR ordinari reali, senza alcun importo:
    # issue #32, non deve piu' far scattare l'anomalia (rumore innocuo).
    rows = _happy_path_rows()
    idx = rows.index(next(r for r in rows if r.text == "ADDIZIONALI ANNO IMPON/RATA"))
    rows.insert(idx, trow(429.0, "CTB. DED. CTB.NON DED."))
    doc = _doc(rows)
    dto = s.map_document(doc)
    assert not any(a.tipo == "righe_non_mappate" for a in dto.anomalies)
    assert "CTB. DED. CTB.NON DED." in dto.unrecognized_row_texts


def test_map_document_righe_non_mappate_con_importo_genera_anomalia():
    rows = _happy_path_rows()
    idx = rows.index(next(r for r in rows if r.text == "ADDIZIONALI ANNO IMPON/RATA"))
    rows.insert(idx, trow(429.0, "Voce non riconosciuta 123,45"))
    doc = _doc(rows)
    dto = s.map_document(doc)
    anomalia = next(a for a in dto.anomalies if a.tipo == "righe_non_mappate")
    assert "1 righe con importo non mappate (su 1 righe totali" in anomalia.messaggio


def test_map_document_totali_mancanti_forza_error():
    rows = [r for r in _happy_path_rows() if r.top not in (633.0, 641.0, 665.0)]
    doc = _doc(rows)
    dto = s.map_document(doc)
    assert any(a.tipo == "totali_mancanti" and a.severita.value == "error" for a in dto.anomalies)


def test_map_document_iban_non_valido():
    rows = [r for r in _happy_path_rows() if r.top != 633.0]
    rows.append(Row(top=633.0, words=[w("IT00A0000000000000000000000", 56)]))
    doc = _doc(rows)
    dto = s.map_document(doc)
    assert any(a.tipo == "iban_non_valido" for a in dto.anomalies)
