"""Regressione per issue GH #4 (glitch font Zucchetti Z->2 su codici causale,
O->0 su IBAN), GH #5 (carattere spurio anteposto al codice causale) e
GH #6/#7/#8 (righe della sezione voci senza codice causale proprio: rumore di
estrazione da scartare vs note di continuazione da agganciare alla voce
precedente). Usa Row/Word sintetici (nessun cedolino reale, nessun dato
personale) perche' i campioni reali sono gitignored. Migrato da
scripts/test_issue4_font_corruption.py."""

from payroll_ingest.extraction import Row, Word
from payroll_ingest.templates import zucchetti as z


def word(text: str, x0: float) -> Word:
    return Word(text=text, x0=x0, x1=x0 + len(text) * 5, top=100.0, bottom=110.0)


def text_row(top: float, text: str) -> Row:
    x = 30.0
    words = []
    for token in text.split(" "):
        words.append(word(token, x))
        x += len(token) * 5 + 10
    return Row(top=top, words=words)


def test_codice_corrotto_grammaticalmente_impossibile_viene_mappato():
    # 2P9960 da ZP9960
    row = Row(top=100.0, words=[word("2P9960", 30), word("Arrotond.", 60), word("mese", 100), word("pr.", 130)])
    result = z._parse_causale_row(row)
    assert result is not None
    payline, correction = result
    assert payline.codice == "ZP9960"
    assert correction == ("2P9960", "ZP9960", "font_digit_lettera")


def test_codice_corrotto_che_combacia_per_caso_con_code_re_non_alterato():
    # Z00020 -> 200020: nessun checksum disponibile per confermare la correzione,
    # quindi il codice non va alterato silenziosamente.
    row = Row(top=110.0, words=[word("200020", 30), word("Retribuzione", 60), word("Ordinaria", 110)])
    result = z._parse_causale_row(row)
    assert result is not None
    payline, correction = result
    assert payline.codice == "200020"
    assert correction is None
    assert z._SUSPECT_LEADING_2_RE.match("200020")


def test_codice_valido_non_modificato():
    codice, tipo_correzione = z._recover_causale_code("F02000")
    assert codice == "F02000"
    assert tipo_correzione is None


def test_carattere_spurio_anteposto_al_codice_viene_rimosso():
    # '\F03020' su 07.pdf (issue GH #5)
    row = Row(top=120.0, words=[word("\\F03020", 30), word("Ritenute", 60), word("IRPEF", 100), word("1.560,21", 460)])
    result = z._parse_causale_row(row)
    assert result is not None
    payline, correction = result
    assert payline.codice == "F03020"
    assert correction == ("\\F03020", "F03020", "prefisso_spurio")


def _iban_sintetico_valido() -> str:
    bban = "O0542811101000000123456"  # CIN 'O' + 5 ABI + 5 CAB + 12 conto
    for cc in range(100):
        candidate = f"IT{cc:02d}{bban}"
        if z._iban_mod97_valid(candidate):
            return candidate
    raise AssertionError("nessun IBAN sintetico checksum-valido trovato")


def test_iban_con_cin_corrotto_o_a_0_viene_corretto():
    iban_valido = _iban_sintetico_valido()
    cin_pos = 4
    assert iban_valido[cin_pos] == "O"
    iban_corrotto = iban_valido[:cin_pos] + "0" + iban_valido[cin_pos + 1 :]
    recovered, was_corrected = z._recover_iban(iban_corrotto)
    assert was_corrected
    assert recovered == iban_valido


def test_iban_non_recuperabile_resta_invariato():
    iban_non_recuperabile = "IT60" + "5" + "0542811101000000123456"[1:]
    recovered, was_corrected = z._recover_iban(iban_non_recuperabile)
    assert not was_corrected
    assert recovered == iban_non_recuperabile


def test_iban_gia_valido_non_modificato():
    iban_valido = _iban_sintetico_valido()
    recovered, was_corrected = z._recover_iban(iban_valido)
    assert recovered == iban_valido
    assert not was_corrected


def test_righe_voce_senza_codice_causale_proprio():
    # issue GH #6/#7/#8: nota di continuazione agganciata, rumore scartato.
    header_row = text_row(200.0, "VOCI VARIABILI DEL MESE IMPORTO BASE RIFERIMENTO TRATTENUTE COMPETENZE")
    causale_row = Row(
        top=210.0,
        words=[word("000096", 30), word("Premio", 60), word("per", 110), word("obiettivi", 140), word("33.498,00", 460)],
    )
    nota_row = text_row(220.0, "MBO")
    rumore_row = text_row(230.0, "1")
    boundary_row = text_row(240.0, "Retribuzione utile T.F.R.")

    pay_lines, unmapped, _ = z._extract_causale_rows([header_row, causale_row, nota_row, rumore_row, boundary_row])

    assert len(pay_lines) == 1
    assert pay_lines[0].note == "MBO"
    assert unmapped == []
