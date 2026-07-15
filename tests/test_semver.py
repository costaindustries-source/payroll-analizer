"""Test per il parsing/confronto SemVer dei tag (formato vX.Y.Z)."""

from payroll_cli.semver import latest, parse, sort_tags, tags_after


def test_parse_valid():
    assert parse("v1.2.3") == (1, 2, 3)
    assert parse("v0.0.1") == (0, 0, 1)
    assert parse("v10.20.30") == (10, 20, 30)


def test_parse_invalid():
    assert parse("1.2.3") is None  # manca la 'v'
    assert parse("v1.2") is None  # incompleto
    assert parse("v1.2.3.4") is None  # troppi segmenti
    assert parse("va.b.c") is None  # non numerico
    assert parse("") is None
    assert parse("v1.2.3-rc1") is None  # suffisso non supportato


def test_sort_tags_orders_numerically_not_lexically():
    # v2.0.0 < v10.0.0 numericamente, ma lessicograficamente sarebbe il contrario
    tags = ["v10.0.0", "v2.0.0", "v1.0.0"]
    assert sort_tags(tags) == ["v1.0.0", "v2.0.0", "v10.0.0"]


def test_sort_tags_ignores_invalid_silently():
    tags = ["v1.0.0", "not-a-tag", "v0.5.0", "vX.Y.Z"]
    assert sort_tags(tags) == ["v0.5.0", "v1.0.0"]


def test_sort_tags_empty():
    assert sort_tags([]) == []


def test_latest_returns_highest():
    assert latest(["v1.0.0", "v1.2.0", "v1.1.0"]) == "v1.2.0"


def test_latest_empty_or_all_invalid_returns_none():
    assert latest([]) is None
    assert latest(["not-a-tag"]) is None


def test_tags_after_baseline():
    tags = ["v1.0.0", "v1.1.0", "v1.2.0", "v2.0.0"]
    assert tags_after(tags, "v1.1.0") == ["v1.2.0", "v2.0.0"]


def test_tags_after_baseline_is_latest_returns_empty():
    tags = ["v1.0.0", "v1.1.0"]
    assert tags_after(tags, "v1.1.0") == []


def test_tags_after_none_baseline_returns_all_valid_ordered():
    tags = ["v1.1.0", "v1.0.0", "invalid"]
    assert tags_after(tags, None) == ["v1.0.0", "v1.1.0"]


def test_tags_after_invalid_baseline_returns_all_valid_ordered():
    tags = ["v1.1.0", "v1.0.0"]
    assert tags_after(tags, "not-semver") == ["v1.0.0", "v1.1.0"]
