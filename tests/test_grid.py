"""Test delle primitive per tabelle a celle (templates/_grid.py). Geometria
sintetica: nessun PDF reale (i campioni sono gitignored, dati personali)."""

import re
from decimal import Decimal

from payroll_ingest.extraction import VLine, Word
from payroll_ingest.templates import _grid as g

# Tabella a 4 celle, con bordo esterno sinistro doppio come nei cedolini.
EDGES = [34.3, 35.5, 105.0, 171.0, 237.0]
TOP, BOTTOM = 700.0, 730.0


def vlines(edges=EDGES, top=TOP, bottom=BOTTOM) -> list[VLine]:
    return [VLine(x=x, top=top, bottom=bottom) for x in edges]


def word(text: str, x0: float, x1: float, y: float = 715.0) -> Word:
    return Word(text=text, x0=x0, x1=x1, top=y - 5, bottom=y + 5)


def test_geo_lines_raggruppa_per_centro_verticale_e_ordina_per_x0():
    words = [word("B", 200, 210, y=100), word("A", 50, 60, y=101), word("C", 50, 60, y=140)]
    lines = g.geo_lines(words)
    assert [ln.text for ln in lines] == ["A B", "C"]
    assert lines[0].y < lines[1].y


def test_geo_lines_vuoto():
    assert g.geo_lines([]) == []


def test_cell_bounds_fonde_i_bordi_doppi():
    bounds = g.cell_bounds(vlines(), y=715.0)
    assert len(bounds) == 3
    assert bounds[0][0] == (34.3 + 35.5) / 2
    assert bounds[-1][1] == 237.0


def test_cell_bounds_ignora_linee_che_non_attraversano_y():
    lines = vlines() + [VLine(x=150.0, top=500.0, bottom=520.0)]
    assert len(g.cell_bounds(lines, y=715.0)) == 3


def test_cell_bounds_scarta_celle_troppo_strette():
    lines = vlines([35.0, 105.0, 112.0, 171.0])
    bounds = g.cell_bounds(lines, y=715.0)
    assert [(round(a), round(b)) for a, b in bounds] == [(35, 105), (112, 171)]


def test_cell_bounds_rispetta_min_x():
    lines = vlines([20.0, 31.0, 35.0, 105.0, 171.0])
    assert len(g.cell_bounds(lines, y=715.0, min_x=33.0)) == 2


def test_cell_index_usa_il_centro_della_parola():
    bounds = g.cell_bounds(vlines(), y=715.0)
    # x0 ricade nella cella 0 ma il centro e' nella cella 1
    assert g.cell_index(bounds, word("x", 100.0, 130.0)) == 1
    assert g.cell_index(bounds, word("x", 50.0, 60.0)) == 0
    assert g.cell_index(bounds, word("x", 300.0, 310.0)) is None


HEADER_PATTERNS = [re.compile(p) for p in ("Alfa", "Beta", "Gamma")]


def _header(y=690.0):
    return g.GeoLine(y=y, words=[word("Alfa", 50, 80, y), word("Beta", 120, 150, y), word("Gamma", 180, 215, y)])


def _values(words, y=715.0):
    return g.GeoLine(y=y, words=words)


def test_value_line_below_ritorna_la_riga_con_importi():
    lines = [_header(), _values([word("1,00", 50, 70)])]
    assert g.value_line_below(lines, 0) is lines[1]


def test_value_line_below_none_se_copia_vuota():
    lines = [_header(), _values([word(" ", 50, 70), word("testo", 120, 150)])]
    assert g.value_line_below(lines, 0) is None


def test_value_line_below_none_se_troppo_lontana():
    lines = [_header(y=100.0), _values([word("1,00", 50, 70)], y=300.0)]
    assert g.value_line_below(lines, 0) is None


def test_value_line_below_none_se_header_e_ultima_riga():
    assert g.value_line_below([_header()], 0) is None


def test_read_header_value_row_assegna_per_cella_con_cella_vuota_in_mezzo():
    values = _values([word("1,00", 50, 70), word("3,00", 180, 200)])
    row = g.read_header_value_row(vlines(), _header(), values, HEADER_PATTERNS)
    assert row == [Decimal("1.00"), None, Decimal("3.00")]


def test_read_header_value_row_none_se_il_numero_di_celle_non_torna():
    values = _values([word("1,00", 50, 70)])
    assert g.read_header_value_row(vlines([35.0, 105.0, 171.0]), _header(), values, HEADER_PATTERNS) is None


def test_read_header_value_row_none_se_l_etichetta_e_nella_cella_sbagliata():
    scambiata = g.GeoLine(y=690.0, words=[word("Beta", 50, 80), word("Alfa", 120, 150), word("Gamma", 180, 215)])
    values = _values([word("1,00", 50, 70)])
    assert g.read_header_value_row(vlines(), scambiata, values, HEADER_PATTERNS) is None


def test_read_header_value_row_none_con_due_importi_nella_stessa_cella():
    values = _values([word("1,00", 50, 70), word("2,00", 80, 100)])
    assert g.read_header_value_row(vlines(), _header(), values, HEADER_PATTERNS) is None


def test_find_lines_restituisce_gli_indici_che_matchano():
    lines = [g.GeoLine(y=1.0, words=[word("uno", 0, 1)]), g.GeoLine(y=2.0, words=[word("due", 0, 1)])]
    assert g.find_lines(lines, re.compile("due")) == [1]
