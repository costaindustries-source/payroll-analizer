from datetime import date
from decimal import Decimal

from payroll_ingest.normalize import (
    find_amounts,
    normalize_label,
    parse_amount,
    parse_date_ddmmyyyy,
    parse_italian_month_year,
)


def test_normalize_label_strips_spaces_and_punctuation():
    assert normalize_label("Totale Competenze") == "totalecompetenze"


def test_normalize_label_removes_s_for_font_glitch():
    # lo spazio nell'header a volte decodifica come 's': rimuovendo tutte le
    # 's' da entrambi i lati il confronto resta stabile
    assert normalize_label("Totale sCompetenze") == normalize_label("Totale Competenze")


def test_normalize_label_case_insensitive():
    assert normalize_label("IMPORTO") == normalize_label("importo")


def test_parse_amount_simple_integer():
    assert parse_amount("128") == Decimal("128")


def test_parse_amount_italian_decimal_with_thousands():
    assert parse_amount("1.234,56") == Decimal("1234.56")


def test_parse_amount_negative_with_matched_parentheses():
    assert parse_amount("(128,00)") == Decimal("-128.00")


def test_parse_amount_negative_with_open_brace_glitch():
    assert parse_amount("{128,00)") == Decimal("-128.00")


def test_parse_amount_negative_open_paren_only():
    assert parse_amount("(128,00") == Decimal("-128.00")


def test_parse_amount_negative_close_paren_fused_no_space():
    # issue GH #3: ')' di chiusura fusa nel token senza spazio
    assert parse_amount("297,10)") == Decimal("-297.10")


def test_parse_amount_invalid_token_returns_none():
    assert parse_amount("abc") is None


def test_parse_amount_strips_whitespace():
    assert parse_amount("  42,50  ") == Decimal("42.50")


def test_find_amounts_extracts_multiple_tokens():
    assert find_amounts("Base 1.234,56 Trattenuta 128,00 Altro 5") == ["1.234,56", "128,00", "5"]


def test_find_amounts_no_match_returns_empty_list():
    assert find_amounts("nessun numero qui") == []


def test_parse_italian_month_year_valid():
    assert parse_italian_month_year("Agosto 2022") == (8, 2022)


def test_parse_italian_month_year_with_trailing_text():
    assert parse_italian_month_year("Dicembre 2023 AGG.") == (12, 2023)


def test_parse_italian_month_year_unknown_month_returns_none():
    assert parse_italian_month_year("Marzone 2022") is None


def test_parse_italian_month_year_no_match_returns_none():
    assert parse_italian_month_year("nessuna data qui") is None


def test_parse_date_ddmmyyyy_valid():
    assert parse_date_ddmmyyyy("Emesso il 15-07-2025 a Roma") == date(2025, 7, 15)


def test_parse_date_ddmmyyyy_no_match_returns_none():
    assert parse_date_ddmmyyyy("nessuna data") is None


def test_parse_date_ddmmyyyy_invalid_calendar_date_returns_none():
    assert parse_date_ddmmyyyy("31-02-2025") is None
