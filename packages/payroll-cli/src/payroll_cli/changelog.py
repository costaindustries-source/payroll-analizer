"""Estrae la sezione di CHANGELOG.md relativa a un tag, per mostrarla in
'payroll update check' senza dover aprire il file a mano."""

from __future__ import annotations

import re
from pathlib import Path

_SECTION_RE = re.compile(r"^## \[(v\d+\.\d+\.\d+|Non rilasciato)\]", re.MULTILINE)


def section_for_tag(repo_root: Path, tag: str) -> str | None:
    changelog = repo_root / "CHANGELOG.md"
    if not changelog.is_file():
        return None
    text = changelog.read_text(encoding="utf-8")
    matches = list(_SECTION_RE.finditer(text))
    for idx, match in enumerate(matches):
        if match.group(1) == tag:
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            return text[start:end].strip()
    return None
