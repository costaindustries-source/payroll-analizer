"""Suite di copertura per il template Zucchetti (packages/payroll-ingest/src/
payroll_ingest/templates/zucchetti.py), estesa oltre test_font_corruption.py
(che resta dedicato ai soli scenari di corruzione font/OCR delle issue GH
#4-#8). Qui: is_zucchetti_document, map_document end-to-end e tutte le
funzioni di estrazione (header, periodo, TFR, ferie/permessi, progressivi,
tasse, totali) con dato presente e dato assente, piu' i rami di
fallback/errore non ancora esercitati. Nessun PDF reale: Row/Word sintetici
come nel resto della suite (i campioni reali sono gitignored, dati personali)."""

from decimal import Decimal
from pathlib import Path

from payroll_ingest.dto import PayLineCategory, PayLineDTO, PeriodType
from payroll_ingest.extraction import RawExtractedDocument, RawPage, Row, Word
from payroll_ingest.templates import zucchetti as z


def w(text: str, x0: float, top: float = 100.0) -> Word:
    return Word(text=text, x0=x0, x1=x0 + len(text) * 5 + 2, top=top, bottom=top + 10)


def trow(top: float, text: str) -> Row:
    # Come text_row in test_font_corruption.py: token separati da spazio,
    # posizionati con x0 crescente. Usato per le righe dove conta solo il
    # testo complessivo (le regex operano su row.text), non la colonna x.
    x = 30.0
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


def _iban_valido() -> str:
    bban = "O0542811101000000123456"  # CIN 'O' + 5 ABI + 5 CAB + 12 conto
    for cc in range(100):
        candidate = f"IT{cc:02d}{bban}"
        if z._iban_mod97_valid(candidate):
            return candidate
    raise AssertionError("nessun IBAN sintetico checksum-valido trovato")


CF_VALIDO = "RSSMRA80A01H501U"
CF_CHECKSUM_ERRATO = "RSSMRA80A01H501A"


# ---------------------------------------------------------------------------
# is_zucchetti_document
# ---------------------------------------------------------------------------


def test_is_zucchetti_document_riconosce_ancora_esplicita():
    doc = _doc([trow(10.0, "Codice Azienda Ragione Sociale")])
    assert z.is_zucchetti_document(doc) is True


def test_is_zucchetti_document_fallback_su_riga_codice_azienda():
    # Ancora principale corrotta/assente ma la riga "codice + ragione sociale"
    # sotto resta leggibile (v. is_zucchetti_document, fallback).
    doc = _doc([trow(10.0, "123456 ACME SPA")])
    assert z.is_zucchetti_document(doc) is True


def test_is_zucchetti_document_non_riconosciuto():
    doc = _doc([trow(10.0, "Documento Generico Senza Ancora")])
    assert z.is_zucchetti_document(doc) is False


def test_is_zucchetti_document_guarda_solo_la_prima_pagina():
    solo_seconda = _doc(
        [trow(10.0, "Documento Generico")],
        extra_pages=[[trow(10.0, "Codice Azienda Ragione Sociale")]],
    )
    assert z.is_zucchetti_document(solo_seconda) is False

    solo_prima = _doc(
        [trow(10.0, "Codice Azienda Ragione Sociale")],
        extra_pages=[[trow(10.0, "Documento Generico")]],
    )
    assert z.is_zucchetti_document(solo_prima) is True


# ---------------------------------------------------------------------------
# _parse_header
# ---------------------------------------------------------------------------


def test_parse_header_estrae_azienda_dipendente_date_e_tipocosto():
    rows = [
        trow(70.0, "123456 REVO INSURANCE SPA"),
        trow(80.0, "Via Roma 1 Aut. 12345"),
        trow(90.0, "20100 MILANO (MI)"),
        trow(100.0, "Sede Territoriale Del 001 Sede 002"),
        trow(110.0, "12345678901 1234567/01 7654321/01"),
        trow(120.0, f"1234567 ROSSI MARIO {CF_VALIDO}"),
        trow(130.0, "01-01-2020 15-03-2020"),
        trow(140.0, "TipoCosto Agosto 2022"),
    ]
    company, employee, hire_date_str, tipo_costo_text = z._parse_header(rows)

    assert company.codice_azienda == "123456"
    assert company.ragione_sociale == "REVO INSURANCE SPA"
    assert company.indirizzo == "Via Roma 1, 20100 MILANO (MI)"
    assert company.inail_aut == "12345"
    assert company.inail_del == "001"
    assert company.inail_sede == "002"
    assert company.posizione_inps == "1234567/01"
    assert company.pat_inail == "7654321/01"
    assert employee.matricola == "1234567"
    assert employee.cognome_nome == "ROSSI MARIO"
    assert employee.codice_fiscale == CF_VALIDO
    assert hire_date_str == "15-03-2020"
    assert tipo_costo_text == "TipoCosto Agosto 2022"


def test_parse_header_righe_assenti_lascia_campi_vuoti():
    company, employee, hire_date_str, tipo_costo_text = z._parse_header([trow(10.0, "Riga qualunque")])
    assert company.ragione_sociale == ""
    assert company.codice_azienda is None
    assert employee.cognome_nome == ""
    assert employee.codice_fiscale == ""
    assert hire_date_str is None
    assert tipo_costo_text is None


def test_parse_header_ignora_righe_oltre_header_max_top():
    # Una riga che matcherebbe come azienda ma e' oltre _HEADER_MAX_TOP (es. e'
    # in realta' una riga voce della tabella causali, non l'header) va ignorata.
    rows = [trow(z._HEADER_MAX_TOP + 10, "123456 NON AZIENDA HEADER")]
    company, _, _, _ = z._parse_header(rows)
    assert company.ragione_sociale == ""


# ---------------------------------------------------------------------------
# _codice_fiscale_checksum_valido
# ---------------------------------------------------------------------------


def test_codice_fiscale_checksum_valido_true():
    assert z._codice_fiscale_checksum_valido(CF_VALIDO) is True


def test_codice_fiscale_checksum_errato():
    assert z._codice_fiscale_checksum_valido(CF_CHECKSUM_ERRATO) is False


def test_codice_fiscale_lunghezza_errata():
    assert z._codice_fiscale_checksum_valido("TROPPOCORTO") is False


def test_codice_fiscale_carattere_non_valido():
    # Un carattere fuori dalle tabelle (es. minuscolo) fa scattare il KeyError
    # gestito esplicitamente, non un'eccezione non gestita.
    invalido = "rssmra80a01h501u"
    assert z._codice_fiscale_checksum_valido(invalido) is False


# ---------------------------------------------------------------------------
# _detect_period_type
# ---------------------------------------------------------------------------


def _line(descrizione: str) -> PayLineDTO:
    return PayLineDTO(codice=None, descrizione=descrizione, categoria=PayLineCategory.ALTRO, is_recognized=True)


def test_detect_period_type_da_tipocosto_agg():
    assert z._detect_period_type("Dicembre 2023 AGG.", []) == PeriodType.MENSILITA_AGGIUNTIVA


def test_detect_period_type_maggio_non_da_falso_positivo_su_agg():
    assert z._detect_period_type("Maggio 2022", []) == PeriodType.ORDINARIO


def test_detect_period_type_da_causale_mensilita():
    assert z._detect_period_type(None, [_line("Arretrato mensilita corrente")]) == PeriodType.MENSILITA_AGGIUNTIVA


def test_detect_period_type_da_causale_conguaglio():
    assert z._detect_period_type(None, [_line("Voce Cong. annuale")]) == PeriodType.CONGUAGLIO


def test_detect_period_type_ordinario_di_default():
    assert z._detect_period_type(None, []) == PeriodType.ORDINARIO


# ---------------------------------------------------------------------------
# _classify_causale
# ---------------------------------------------------------------------------


def test_classify_causale_tutte_le_categorie():
    assert z._classify_causale("F.do sostegno pensione") == PayLineCategory.CONTRIBUTO
    assert z._classify_causale("Ferie godute") == PayLineCategory.ASSENZA
    assert z._classify_causale("Ticket elettronico") == PayLineCategory.BENEFIT
    assert z._classify_causale("Spese carta di credito") == PayLineCategory.RIMBORSO
    assert z._classify_causale("Retribuzione ordinaria") == PayLineCategory.RETRIBUZIONE
    assert z._classify_causale("Voce completamente sconosciuta") == PayLineCategory.ALTRO


# ---------------------------------------------------------------------------
# _column_of / _looks_like_data / _first_amount / _split_amount_zone
# ---------------------------------------------------------------------------


def test_column_of_soglie():
    assert z._column_of(z.IMPORTO_BASE_MIN - 0.1) == "descrizione"
    assert z._column_of(z.IMPORTO_BASE_MIN) == "importo_base"
    assert z._column_of(z.RIFERIMENTO_MIN - 0.1) == "importo_base"
    assert z._column_of(z.RIFERIMENTO_MIN) == "riferimento"
    assert z._column_of(z.TRATTENUTE_MIN - 0.1) == "riferimento"
    assert z._column_of(z.TRATTENUTE_MIN) == "importo"
    assert z._column_of(9999.0) == "importo"


def test_looks_like_data():
    assert z._looks_like_data("GG") is True
    assert z._looks_like_data("(") is True
    assert z._looks_like_data("1.234,56") is True
    assert z._looks_like_data("Retribuzione") is False


def test_first_amount_ignora_marker_parentesi():
    words = [w("(", 30), w("128,00", 60)]
    assert z._first_amount(words) == Decimal("128.00")


def test_first_amount_nessun_importo():
    assert z._first_amount([w("testo", 30)]) is None


def test_split_amount_zone_con_marker_parentesi_e_trattenuta():
    words = [w("(", 460), w("128,00", 465)]
    trattenuta, competenza = z._split_amount_zone(words)
    assert trattenuta == Decimal("128.00")
    assert competenza is None


def test_split_amount_zone_parentesi_fusa_nel_token():
    # ')' di chiusura fusa nel token senza marker separato (v. issue GH #3).
    trattenuta, competenza = z._split_amount_zone([w("408,00)", 460)])
    assert trattenuta == Decimal("408.00")
    assert competenza is None


def test_split_amount_zone_positivo_sotto_soglia_competenze_e_trattenuta():
    trattenuta, competenza = z._split_amount_zone([w("100,00", 460)])
    assert trattenuta == Decimal("100.00")
    assert competenza is None


def test_split_amount_zone_positivo_sopra_soglia_competenze_e_competenza():
    trattenuta, competenza = z._split_amount_zone([w("100,00", 520)])
    assert trattenuta is None
    assert competenza == Decimal("100.00")


def test_split_amount_zone_vuota():
    assert z._split_amount_zone([]) == (None, None)


def test_split_amount_zone_ignora_token_non_numerico_prima_del_vero_importo():
    trattenuta, competenza = z._split_amount_zone([w("N/D", 460), w("100,00", 465)])
    assert trattenuta == Decimal("100.00")
    assert competenza is None


def test_parse_causale_row_aliquota_percentuale():
    # Colonna RIFERIMENTO con unita' "%": il valore numerico va in aliquota,
    # non in quantita' (v. _parse_causale_row).
    row = Row(
        top=100.0,
        words=[w("F09960", 30), w("Ctr.prev", 60), w("9,19", 350), w("%", 380)],
    )
    result = z._parse_causale_row(row)
    assert result is not None
    payline, _ = result
    assert payline.aliquota == Decimal("9.19")
    assert payline.quantita is None
    assert payline.unita == "%"


# ---------------------------------------------------------------------------
# _recover_causale_code / _leading_code_index (casi non gia' in
# test_font_corruption.py)
# ---------------------------------------------------------------------------


def test_recover_causale_code_non_recuperabile_resta_invariato():
    codice, tipo = z._recover_causale_code("??????")
    assert codice == "??????"
    assert tipo is None


def test_recover_causale_code_troppo_corto_per_qualunque_euristica():
    codice, tipo = z._recover_causale_code("2")
    assert codice == "2"
    assert tipo is None


def test_leading_code_index_con_due_marker_spuri():
    words = [w("*", 30), w("'", 60), w("F02000", 90)]
    assert z._leading_code_index(words) == 2


def test_leading_code_index_oltre_la_finestra_tollerata_restituisce_none():
    words = [w("*", 30), w("*", 60), w("*", 90), w("F02000", 120)]
    assert z._leading_code_index(words) is None


def test_parse_causale_row_senza_descrizione_restituisce_none():
    # Il codice e' seguito immediatamente da un dato: nessuna parola di
    # descrizione tra i due, quindi la riga non e' una voce valida.
    row = Row(top=100.0, words=[w("000096", 30), w("1.500,00", 210)])
    assert z._parse_causale_row(row) is None


# ---------------------------------------------------------------------------
# _fallback_causale_bounds / _extract_causale_rows (casi non gia' coperti)
# ---------------------------------------------------------------------------


def test_fallback_causale_bounds_usa_prima_riga_causale_riconoscibile():
    rows = [
        trow(300.0, "TESTATA COLONNE CORROTTA ILLEGGIBILE"),
        Row(top=310.0, words=[w("000096", 30), w("Premio", 60), w("obiettivi", 100), w("100,00", 460)]),
        trow(320.0, "Retribuzione utile T.F.R."),
    ]
    start_idx, end_idx = z._fallback_causale_bounds(rows)
    assert start_idx == 1
    assert end_idx == 2


def test_fallback_causale_bounds_nessuna_riga_causale_trovata():
    rows = [trow(300.0, "Nessun codice causale qui dentro")]
    start_idx, end_idx = z._fallback_causale_bounds(rows)
    assert start_idx is None
    assert end_idx == len(rows)


def test_extract_causale_rows_riga_orfana_non_mappata():
    header = trow(200.0, "IMPORTO BASE RIFERIMENTO TRATTENUTE COMPETENZE")
    orfana = trow(210.0, "Testo sconosciuto senza codice causale")
    causale = Row(top=220.0, words=[w("000096", 30), w("Premio", 60), w("obiettivi", 100), w("100,00", 460)])
    boundary = trow(230.0, "Retribuzione utile T.F.R.")

    pay_lines, unmapped, corrections = z._extract_causale_rows([header, orfana, causale, boundary])

    assert unmapped == ["Testo sconosciuto senza codice causale"]
    assert len(pay_lines) == 1
    assert corrections == []


def test_extract_causale_rows_etichetta_sezione_vuota_scartata():
    header = trow(200.0, "IMPORTO BASE RIFERIMENTO TRATTENUTE COMPETENZE")
    sezione_vuota = trow(210.0, "CONGUAGLIO")
    boundary = trow(220.0, "Retribuzione utile T.F.R.")

    pay_lines, unmapped, _ = z._extract_causale_rows([header, sezione_vuota, boundary])

    assert pay_lines == []
    assert unmapped == []


def test_extract_causale_rows_senza_header_ne_fallback_restituisce_vuoto():
    rows = [trow(300.0, "Nessuna intestazione e nessun codice causale")]
    pay_lines, unmapped, corrections = z._extract_causale_rows(rows)
    assert (pay_lines, unmapped, corrections) == ([], [], [])


def test_extract_causale_rows_usa_fallback_quando_header_illeggibile():
    # _fallback_causale_bounds scarta le righe con top < _HEADER_MAX_TOP: la
    # riga causale deve stare oltre quella soglia per essere considerata.
    header_corrotto = trow(200.0, "TESTATA ILLEGGIBILE GLYPH CORROTTI")
    causale = Row(top=270.0, words=[w("000096", 30), w("Premio", 60), w("obiettivi", 100), w("100,00", 460)])
    boundary = trow(280.0, "Retribuzione utile T.F.R.")

    pay_lines, unmapped, _ = z._extract_causale_rows([header_corrotto, causale, boundary])

    assert len(pay_lines) == 1
    assert pay_lines[0].codice == "000096"
    assert unmapped == []


# ---------------------------------------------------------------------------
# _extract_tax
# ---------------------------------------------------------------------------


def test_extract_tax_mappa_i_codici_fiscali_noti_e_li_rimuove_dalle_pay_lines():
    pay_lines = [
        PayLineDTO(
            codice="F02000", descrizione="Imponibile IRPEF", categoria=PayLineCategory.ALTRO,
            is_recognized=True, competenza=Decimal("2000.00"),
        ),
        PayLineDTO(
            codice="F02010", descrizione="IRPEF lorda", categoria=PayLineCategory.ALTRO,
            is_recognized=True, competenza=Decimal("300.00"),
        ),
        PayLineDTO(
            codice="F02500", descrizione="Detrazioni", categoria=PayLineCategory.ALTRO,
            is_recognized=True, competenza=Decimal("50.00"),
        ),
        PayLineDTO(
            codice="F03020", descrizione="Ritenute IRPEF", categoria=PayLineCategory.ALTRO,
            is_recognized=True, trattenuta=Decimal("250.00"),
        ),
        PayLineDTO(
            codice="C12340", descrizione="Contributo IVS", categoria=PayLineCategory.CONTRIBUTO,
            is_recognized=True, trattenuta=Decimal("100.00"),
        ),
    ]
    tax = z._extract_tax(pay_lines, [])

    assert tax.imponibile_irpef == Decimal("2000.00")
    assert tax.irpef_lorda == Decimal("300.00")
    assert tax.detrazioni_lav_dip == Decimal("50.00")
    assert tax.ritenute_irpef == Decimal("250.00")
    assert len(pay_lines) == 1
    assert pay_lines[0].codice == "C12340"


def test_extract_tax_addizionali_regionale_comunale_acconto():
    rows = [
        trow(400.0, "Addizionale regionale 2021 LOM Residuo 12,50"),
        trow(410.0, "Addizionale comunale 8,40"),
        trow(420.0, "Acconto addiz. comunale 4,20"),
    ]
    tax = z._extract_tax([], rows)

    assert tax.addizionale_regionale == Decimal("12.50")
    assert tax.addizionale_regionale_regione == "LOM"
    assert tax.addizionale_comunale == Decimal("8.40")
    assert tax.acconto_addizionale_comunale == Decimal("4.20")


def test_extract_tax_addizionale_regionale_senza_regione_riconoscibile():
    rows = [trow(400.0, "Addizionale regionale 12,50")]
    tax = z._extract_tax([], rows)
    assert tax.addizionale_regionale == Decimal("12.50")
    assert tax.addizionale_regionale_regione is None


def test_extract_tax_senza_dati_resta_tutto_none():
    tax = z._extract_tax([], [trow(400.0, "Riga qualunque senza rilevanza fiscale")])
    assert tax.imponibile_irpef is None
    assert tax.addizionale_regionale is None


# ---------------------------------------------------------------------------
# _extract_tfr
# ---------------------------------------------------------------------------


def test_extract_tfr_campi_semplici():
    rows = [
        trow(300.0, "Retribuzione utile T.F.R. 1.500,00"),
        trow(310.0, "Quota T.F.R. a Fondi 300,00"),
    ]
    tfr = z._extract_tfr(rows)
    assert tfr.retribuzione_utile_tfr == Decimal("1500.00")
    assert tfr.quota_tfr_fondi == Decimal("300.00")


def test_extract_tfr_sottotabella_colonne_allineate_per_x0():
    header = Row(
        top=310.0,
        words=[w("Rivalutaz.", 100), w("Imp.rival.", 200), w("Quota", 300), w("anno", 340), w("Anticipi", 400)],
    )
    valori = Row(top=320.0, words=[w("50,00", 105), w("1.000,00", 205), w("200,00", 305)])
    tfr = z._extract_tfr([header, valori])

    assert tfr.rivalutazione == Decimal("50.00")
    assert tfr.imponibile_rivalutazione == Decimal("1000.00")
    assert tfr.quota_anno == Decimal("200.00")
    assert tfr.anticipi is None  # nessun valore vicino alla colonna Anticipi


def test_extract_tfr_senza_dati_resta_tutto_none():
    tfr = z._extract_tfr([trow(300.0, "Riga qualunque")])
    assert tfr.retribuzione_utile_tfr is None
    assert tfr.rivalutazione is None


def test_extract_tfr_sottotabella_ignora_token_non_numerico_nella_riga_valori():
    header = Row(top=310.0, words=[w("Rivalutaz.", 100), w("Imp.rival.", 200)])
    valori = Row(top=320.0, words=[w("50,00", 105), w("n/d", 150), w("1.000,00", 205)])
    tfr = z._extract_tfr([header, valori])
    assert tfr.rivalutazione == Decimal("50.00")
    assert tfr.imponibile_rivalutazione == Decimal("1000.00")


# ---------------------------------------------------------------------------
# _extract_leave_balances
# ---------------------------------------------------------------------------


def test_extract_leave_balances_riga_ferie():
    header = trow(330.0, "Maturato Goduto Residuo Residuo AP")
    ferie = Row(top=340.0, words=[w("Ferie", 30), w("20,00", 90), w("15,00", 150), w("5,00", 210)])
    balances = z._extract_leave_balances([header, ferie])

    assert len(balances) == 1
    assert balances[0].tipo == "Ferie"
    assert balances[0].maturato == Decimal("20.00")
    assert balances[0].goduto == Decimal("15.00")
    assert balances[0].residuo == Decimal("5.00")
    assert balances[0].residuo_ap is None


def test_extract_leave_balances_header_assente():
    assert z._extract_leave_balances([trow(300.0, "Nessuna intestazione qui")]) == []


def test_extract_leave_balances_ignora_righe_del_blocco_destro():
    header = trow(330.0, "Maturato Goduto Residuo Residuo AP")
    # Blocco TOTALE/ARROTONDAMENTO: x0 >= _LEFT_BLOCK_MAX_X, quindi fuori dal
    # blocco ferie/permessi anche se cade nella finestra di righe successive.
    riga_destra = Row(top=340.0, words=[w("500,00", z._LEFT_BLOCK_MAX_X + 10)])
    assert z._extract_leave_balances([header, riga_destra]) == []


def test_extract_leave_balances_oltre_la_finestra_non_e_considerata():
    header = trow(330.0, "Maturato Goduto Residuo Residuo AP")
    # Righe di riempimento con x0 >= 100 (fuori dal blocco sinistro ferie/
    # permessi, v. condizione left_words[0].x0 >= 100), cosi' da non essere
    # scambiate per candidati validi mentre saturano la finestra di 6 righe.
    riempitivo = [Row(top=340.0 + i * 5, words=[w("Riempimento", 150)]) for i in range(z._LEAVE_ROW_WINDOW)]
    ferie_fuori_finestra = Row(top=999.0, words=[w("Ferie", 30), w("20,00", 90)])
    balances = z._extract_leave_balances([header, *riempitivo, ferie_fuori_finestra])
    assert balances == []


def test_extract_leave_balances_riga_senza_tipo_testuale_viene_scartata():
    # Il primo token e' gia' un dato numerico: nessuna descrizione ("tipo")
    # da associargli, quindi la riga va scartata invece di produrre un
    # LeaveBalanceDTO senza tipo.
    header = trow(330.0, "Maturato Goduto Residuo Residuo AP")
    solo_numero = Row(top=340.0, words=[w("20,00", 30)])
    assert z._extract_leave_balances([header, solo_numero]) == []


def test_extract_leave_balances_riga_con_tipo_ma_senza_importi_viene_scartata():
    header = trow(330.0, "Maturato Goduto Residuo Residuo AP")
    # "GG" e' un token UNIT_TOKENS: fa scattare _looks_like_data (fine
    # descrizione) ma viene poi escluso dal calcolo degli importi, lasciando
    # la lista amounts vuota.
    senza_importi = Row(top=340.0, words=[w("Ferie", 30), w("GG", 90)])
    assert z._extract_leave_balances([header, senza_importi]) == []


# ---------------------------------------------------------------------------
# _extract_progressivi
# ---------------------------------------------------------------------------


def test_extract_progressivi_valori_allineati_per_x0():
    header = Row(
        top=350.0,
        words=[
            w("PROGRESSIVI", 30), w("Imp.", 90), w("INPS", 110), w("Imp.", 160), w("INAIL", 180),
            w("Imp.", 230), w("IRPEF", 250), w("IRPEF", 320), w("pagata", 360),
        ],
    )
    valori = Row(top=360.0, words=[w("10.000,00", 112), w("500,00", 182), w("8.000,00", 252)])
    inps, inail, irpef = z._extract_progressivi([header, valori])

    assert inps == Decimal("10000.00")
    assert inail == Decimal("500.00")
    assert irpef == Decimal("8000.00")


def test_extract_progressivi_ignora_token_non_numerico_nella_riga_valori():
    header = Row(top=350.0, words=[w("PROGRESSIVI", 30), w("Imp.", 90), w("INPS", 110)])
    valori = Row(top=360.0, words=[w("n/d", 90), w("10.000,00", 112)])
    inps, _, _ = z._extract_progressivi([header, valori])
    assert inps == Decimal("10000.00")


def test_extract_progressivi_etichetta_sezione_vuota_continua_la_ricerca():
    vuota = trow(350.0, "PROGRESSIVI")
    header = Row(top=360.0, words=[w("PROGRESSIVI", 30), w("Imp.", 90), w("INPS", 110)])
    valori = Row(top=370.0, words=[w("10.000,00", 112)])

    inps, inail, irpef = z._extract_progressivi([vuota, header, valori])

    assert inps == Decimal("10000.00")
    assert inail is None
    assert irpef is None


def test_extract_progressivi_header_ultima_riga_senza_valori():
    header = Row(top=350.0, words=[w("PROGRESSIVI", 30), w("Imp.", 90), w("INPS", 110)])
    assert z._extract_progressivi([header]) == (None, None, None)


def test_extract_progressivi_assente():
    assert z._extract_progressivi([trow(300.0, "Riga qualunque")]) == (None, None, None)


# ---------------------------------------------------------------------------
# _amount_after_label / _extract_totals
# ---------------------------------------------------------------------------


def test_amount_after_label_prende_importo_dopo_etichetta_non_prima():
    # Simula la fusione OCR di due righe (v. issue GH #12): l'importo di
    # "Ferie" precede l'etichetta sulla stessa riga clusterizzata, quello di
    # "TOTALE TRATTENUTE" la segue: va preso il secondo, non il primo.
    words = [w("Ferie", 30), w("20,00", 90), w("TOTALE", 150), w("TRATTENUTE", 200), w("600,00", 460)]
    label_norm = z_normalize("TOTALE TRATTENUTE")
    assert z._amount_after_label(words, label_norm) == Decimal("600.00")


def z_normalize(text: str) -> str:
    from payroll_ingest.normalize import normalize_label

    return normalize_label(text)


def test_amount_after_label_etichetta_non_trovata_fallback_primo_importo():
    words = [w("100,00", 30), w("200,00", 90)]
    assert z._amount_after_label(words, "etichetta_inesistente") == Decimal("100.00")


def test_amount_after_label_ignora_marker_parentesi_dopo_etichetta():
    label_norm = z_normalize("TOTALE TRATTENUTE")
    words = [w("TOTALE", 30), w("TRATTENUTE", 90), w("(", 150), w("600,00", 200)]
    assert z._amount_after_label(words, label_norm) == Decimal("600.00")


def test_amount_after_label_etichetta_trovata_ma_nessun_importo_dopo():
    label_norm = z_normalize("TOTALE TRATTENUTE")
    words = [w("TOTALE", 30), w("TRATTENUTE", 90), w("testo", 150)]
    assert z._amount_after_label(words, label_norm) is None


def test_extract_totals_completo():
    rows = [
        trow(370.0, "TOTALE COMPETENZE 5.000,00"),
        trow(380.0, "TOTALE TRATTENUTE 600,00"),
        trow(390.0, "NETTO DEL MESE"),
        trow(400.0, "4.400,00"),
    ]
    iban_valido = _iban_valido()
    rows.append(trow(410.0, f"IBAN {iban_valido}"))

    totals = z._extract_totals(rows)

    assert totals.totale_competenze == Decimal("5000.00")
    assert totals.totale_trattenute == Decimal("600.00")
    assert totals.netto_mese == Decimal("4400.00")
    assert totals.iban == iban_valido


def test_extract_totals_netto_su_riga_successiva_alla_seconda():
    rows = [
        trow(390.0, "NETTO DEL MESE"),
        trow(395.0, "testo di riempimento senza importi"),
        trow(400.0, "4.400,00"),
    ]
    totals = z._extract_totals(rows)
    assert totals.netto_mese == Decimal("4400.00")


def test_extract_totals_assenti():
    totals = z._extract_totals([trow(300.0, "Riga qualunque")])
    assert totals.totale_competenze is None
    assert totals.totale_trattenute is None
    assert totals.netto_mese is None
    assert totals.iban is None


# ---------------------------------------------------------------------------
# _recover_iban / _iban_mod97_valid (casi non gia' in test_font_corruption.py)
# ---------------------------------------------------------------------------


def test_recover_iban_lunghezza_errata():
    corto = "IT60" + "0" + "0542811101"
    assert z._recover_iban(corto) == (corto, False)


def test_recover_iban_non_inizia_per_it():
    valido = _iban_valido()
    non_it = "FR" + valido[2:]
    assert z._recover_iban(non_it) == (non_it, False)


def test_recover_iban_cifra_non_confondibile():
    valido = _iban_valido()
    corrotto = valido[:4] + "3" + valido[5:]
    assert z._recover_iban(corrotto) == (corrotto, False)


def test_recover_iban_sostituzione_candidata_non_supera_il_checksum():
    # Cifra confondibile (mappata a una lettera plausibile), ma la lettera
    # "giusta" per questo IBAN e' un'altra: la sostituzione tentata non
    # supera il mod97 e va scartata, non applicata alla cieca.
    valido = _iban_valido()
    assert valido[4] == "O"
    corrotto = valido[:4] + "1" + valido[5:]  # '1' -> 'I', non 'O'
    assert z._recover_iban(corrotto) == (corrotto, False)


def test_iban_mod97_valid_carattere_non_valido_restituisce_false():
    assert z._iban_mod97_valid("IT60!0542811101000000123456") is False


# ---------------------------------------------------------------------------
# map_document end-to-end
# ---------------------------------------------------------------------------


def _documento_completo_valido() -> RawExtractedDocument:
    iban_valido = _iban_valido()
    rows = [
        trow(10.0, "Codice Azienda Ragione Sociale"),
        trow(70.0, "123456 REVO INSURANCE SPA"),
        trow(80.0, "Via Roma 1 Aut. 12345"),
        trow(90.0, "20100 MILANO (MI)"),
        trow(100.0, "Sede Territoriale Del 001 Sede 002"),
        trow(110.0, "12345678901 1234567/01 7654321/01"),
        trow(120.0, f"1234567 ROSSI MARIO {CF_VALIDO}"),
        trow(130.0, "01-01-2020 15-03-2020"),
        trow(140.0, "TipoCosto Agosto 2022"),
        trow(260.0, "IMPORTO BASE RIFERIMENTO TRATTENUTE COMPETENZE"),
        Row(
            top=270.0,
            words=[w("F02000", 30), w("Imponibile", 60), w("IRPEF", 130), w("2.000,00", 520)],
        ),
        Row(
            top=280.0,
            words=[
                w("000096", 30), w("Retribuzione", 60), w("Ordinaria", 140),
                w("1.500,00", 210), w("26", 350), w("GG", 380), w("1.500,00", 520),
            ],
        ),
        Row(
            top=290.0,
            words=[w("C12340", 30), w("Contributo", 60), w("IVS", 130), w("100,00", 460)],
        ),
        trow(300.0, "Retribuzione utile T.F.R. 1.500,00"),
        trow(305.0, "Quota T.F.R. a Fondi 300,00"),
        Row(
            top=310.0,
            words=[w("Rivalutaz.", 100), w("Imp.rival.", 200), w("Quota", 300), w("anno", 340), w("Anticipi", 400)],
        ),
        Row(top=320.0, words=[w("50,00", 105), w("1.000,00", 205), w("200,00", 305)]),
        Row(
            top=350.0,
            words=[
                w("PROGRESSIVI", 30), w("Imp.", 90), w("INPS", 110), w("Imp.", 160), w("INAIL", 180),
                w("Imp.", 230), w("IRPEF", 250),
            ],
        ),
        Row(top=360.0, words=[w("10.000,00", 112), w("500,00", 182), w("8.000,00", 252)]),
        trow(370.0, "TOTALE COMPETENZE 5.000,00"),
        trow(380.0, "TOTALE TRATTENUTE 600,00"),
        trow(390.0, "NETTO DEL MESE"),
        trow(400.0, "4.400,00"),
        trow(410.0, f"IBAN {iban_valido}"),
        trow(430.0, "Maturato Goduto Residuo Residuo AP"),
        Row(top=440.0, words=[w("Ferie", 30), w("20,00", 90), w("15,00", 150), w("5,00", 210)]),
    ]
    return _doc(rows)


def test_map_document_happy_path_estrae_i_campi_principali():
    dto = z.map_document(_documento_completo_valido())

    assert dto.template_name == z.TEMPLATE_NAME
    assert dto.company.codice_azienda == "123456"
    assert dto.company.ragione_sociale == "REVO INSURANCE SPA"
    assert dto.employee.cognome_nome == "ROSSI MARIO"
    assert dto.employee.codice_fiscale == CF_VALIDO
    assert dto.period.mese == 8
    assert dto.period.anno == 2022
    assert dto.period.tipo == PeriodType.ORDINARIO
    assert dto.hire_date is not None and dto.hire_date.isoformat() == "2020-03-15"

    codici = {pl.codice: pl for pl in dto.pay_lines}
    assert set(codici) == {"000096", "C12340"}
    assert codici["000096"].categoria == PayLineCategory.RETRIBUZIONE
    assert codici["000096"].competenza == Decimal("1500.00")
    assert codici["000096"].quantita == Decimal("26")
    assert codici["000096"].unita == "GG"
    assert codici["C12340"].categoria == PayLineCategory.CONTRIBUTO
    assert codici["C12340"].trattenuta == Decimal("100.00")

    assert dto.tax.imponibile_irpef == Decimal("2000.00")
    assert dto.tfr.retribuzione_utile_tfr == Decimal("1500.00")
    assert dto.tfr.quota_tfr_fondi == Decimal("300.00")
    assert dto.tfr.rivalutazione == Decimal("50.00")
    assert len(dto.leave_balances) == 1
    assert dto.leave_balances[0].tipo == "Ferie"
    assert dto.totals.totale_competenze == Decimal("5000.00")
    assert dto.totals.totale_trattenute == Decimal("600.00")
    assert dto.totals.netto_mese == Decimal("4400.00")
    assert dto.totals.imponibile_inps == Decimal("10000.00")
    assert dto.totals.imponibile_inail == Decimal("500.00")
    assert dto.totals.imponibile_irpef == Decimal("8000.00")
    assert dto.totals.iban is not None and len(dto.totals.iban) == 27

    # Documento pulito: nessuna anomalia in nessuno dei rami controllati da
    # map_document (header completo, periodo riconosciuto, data valida,
    # nessuna riga orfana, nessuna correzione, totali/IBAN presenti).
    assert dto.anomalies == []


def test_map_document_codice_fiscale_con_checksum_errato_genera_anomalia_e_azzera_cf():
    rows = [
        trow(70.0, "123456 REVO INSURANCE SPA"),
        trow(120.0, f"1234567 ROSSI MARIO {CF_CHECKSUM_ERRATO}"),
    ]
    dto = z.map_document(_doc(rows))

    assert dto.employee.codice_fiscale == ""
    tipi = {a.tipo for a in dto.anomalies}
    assert "codice_fiscale_non_valido" in tipi
    assert "header_incompleto" not in [a.tipo for a in dto.anomalies if a.campo == "employee.codice_fiscale"]


def test_map_document_codice_fiscale_assente_genera_header_incompleto():
    dto = z.map_document(_doc([trow(70.0, "123456 REVO INSURANCE SPA")]))
    matching = [a for a in dto.anomalies if a.campo == "employee.codice_fiscale"]
    assert len(matching) == 1
    assert matching[0].tipo == "header_incompleto"


def test_map_document_ragione_sociale_assente_genera_anomalia():
    dto = z.map_document(_doc([trow(120.0, f"1234567 ROSSI MARIO {CF_VALIDO}")]))
    tipi_su_company = [a.tipo for a in dto.anomalies if a.campo == "company.ragione_sociale"]
    assert tipi_su_company == ["header_incompleto"]


def test_map_document_periodo_non_riconosciuto_genera_anomalia():
    dto = z.map_document(_doc([trow(140.0, "TipoCosto testo senza mese e anno")]))
    assert dto.period.mese == 0
    assert any(a.tipo == "periodo_non_riconosciuto" for a in dto.anomalies)


def test_map_document_data_assunzione_sintatticamente_valida_ma_calendario_invalido():
    rows = [trow(130.0, "01-01-2020 31-11-2020")]
    dto = z.map_document(_doc(rows))
    assert dto.hire_date is None
    assert any(a.tipo == "data_non_valida" for a in dto.anomalies)


def test_map_document_righe_non_mappate_generano_anomalia_info():
    rows = [
        trow(260.0, "IMPORTO BASE RIFERIMENTO TRATTENUTE COMPETENZE"),
        trow(270.0, "Testo sconosciuto senza codice causale"),
        trow(280.0, "Retribuzione utile T.F.R."),
    ]
    dto = z.map_document(_doc(rows))
    anomalia = next(a for a in dto.anomalies if a.tipo == "righe_non_mappate")
    assert "1 righe" in anomalia.messaggio
    assert dto.unrecognized_row_texts == ["Testo sconosciuto senza codice causale"]


def test_map_document_correzione_causale_e_sospetto_generano_anomalie():
    rows = [
        trow(260.0, "IMPORTO BASE RIFERIMENTO TRATTENUTE COMPETENZE"),
        # 2P9960 -> ZP9960: glitch font confermato su questo documento.
        Row(top=270.0, words=[w("2P9960", 30), w("Arrotond.", 60), w("mese", 100), w("100,00", 460)]),
        # 200020 e' puramente numerico e combacia per caso con _CODE_RE: non
        # corretto, ma segnalato come sospetto perche' nello stesso documento
        # la corruzione Z->2 e' gia' confermata sulla riga precedente.
        Row(top=280.0, words=[w("200020", 30), w("Retribuzione", 60), w("Ordinaria", 130), w("50,00", 460)]),
        trow(290.0, "Retribuzione utile T.F.R."),
    ]
    dto = z.map_document(_doc(rows))

    correzioni = [a for a in dto.anomalies if a.tipo == "codice_causale_corretto_automaticamente"]
    sospetti = [a for a in dto.anomalies if a.tipo == "codice_causale_sospetto"]
    assert len(correzioni) == 1
    assert "ZP9960" in correzioni[0].messaggio
    assert len(sospetti) == 1
    assert "200020" in sospetti[0].messaggio


def test_map_document_iban_corretto_genera_anomalia():
    iban_valido = _iban_valido()
    cin_pos = 4
    assert iban_valido[cin_pos] == "O"
    iban_corrotto = iban_valido[:cin_pos] + "0" + iban_valido[cin_pos + 1 :]
    dto = z.map_document(_doc([trow(410.0, f"IBAN {iban_corrotto}")]))

    assert dto.totals.iban == iban_valido
    anomalia = next(a for a in dto.anomalies if a.tipo == "iban_corretto_automaticamente")
    assert iban_corrotto in anomalia.messaggio
    assert iban_valido in anomalia.messaggio


def test_map_document_totali_mancanti_genera_anomalia_error():
    dto = z.map_document(_doc([trow(70.0, "123456 REVO INSURANCE SPA")]))
    anomalia = next(a for a in dto.anomalies if a.tipo == "totali_mancanti")
    assert "netto_mese" in anomalia.messaggio
    assert "iban" in anomalia.messaggio
    assert anomalia.severita.value == "error"


def test_map_document_pagine_multiple_concatenate_per_totali_e_tfr():
    # v. issue GH #9: i box totali/TFR/IBAN sono solo sull'ultima pagina di un
    # cedolino con conguaglio allegato; l'header e le voci restano sulla prima.
    iban_valido = _iban_valido()
    prima_pagina = [
        trow(70.0, "123456 REVO INSURANCE SPA"),
        trow(120.0, f"1234567 ROSSI MARIO {CF_VALIDO}"),
        trow(260.0, "IMPORTO BASE RIFERIMENTO TRATTENUTE COMPETENZE"),
        Row(top=270.0, words=[w("000096", 30), w("Premio", 60), w("obiettivi", 100), w("100,00", 460)]),
        trow(280.0, "Retribuzione utile T.F.R."),
    ]
    seconda_pagina = [
        trow(50.0, "TOTALE COMPETENZE 1.000,00"),
        trow(60.0, "TOTALE TRATTENUTE 100,00"),
        trow(70.0, "NETTO DEL MESE"),
        trow(80.0, "900,00"),
        trow(90.0, f"IBAN {iban_valido}"),
    ]
    doc = RawExtractedDocument(
        source_path=Path("multi.pdf"),
        pages=[_page(prima_pagina), _page(seconda_pagina)],
    )
    dto = z.map_document(doc)

    assert dto.totals.totale_competenze == Decimal("1000.00")
    assert dto.totals.netto_mese == Decimal("900.00")
    assert dto.totals.iban == iban_valido
    # La sezione voci resta ancorata alla sola prima pagina.
    assert len(dto.pay_lines) == 1
