"""Test per l'estrazione della sezione di CHANGELOG.md relativa a un tag."""

from payroll_cli.changelog import section_for_tag

CHANGELOG_CONTENT = """\
# Changelog

## [Non rilasciato]

- lavori in corso

## [v1.2.0]

- feature B
- feature C

## [v1.1.0]

- feature A

## [v1.0.0]

- prima release
"""


def test_section_for_tag_middle_section(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_CONTENT, encoding="utf-8")
    section = section_for_tag(tmp_path, "v1.1.0")
    assert section == "- feature A"


def test_section_for_tag_first_section_non_rilasciato(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_CONTENT, encoding="utf-8")
    section = section_for_tag(tmp_path, "Non rilasciato")
    assert section == "- lavori in corso"


def test_section_for_tag_top_versioned_section(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_CONTENT, encoding="utf-8")
    section = section_for_tag(tmp_path, "v1.2.0")
    assert section == "- feature B\n- feature C"


def test_section_for_tag_last_section_goes_to_end_of_file(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_CONTENT, encoding="utf-8")
    section = section_for_tag(tmp_path, "v1.0.0")
    assert section == "- prima release"


def test_section_for_tag_unknown_tag_returns_none(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_CONTENT, encoding="utf-8")
    assert section_for_tag(tmp_path, "v9.9.9") is None


def test_section_for_tag_missing_file_returns_none(tmp_path):
    assert section_for_tag(tmp_path, "v1.0.0") is None
