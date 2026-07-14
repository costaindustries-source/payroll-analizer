"""Ordinamento SemVer dei tag (formato vX.Y.Z usato da questo progetto)."""

from __future__ import annotations

import re

_SEMVER_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def parse(tag: str) -> tuple[int, int, int] | None:
    match = _SEMVER_RE.match(tag)
    if not match:
        return None
    a, b, c = match.groups()
    return (int(a), int(b), int(c))


def sort_tags(tags: list[str]) -> list[str]:
    """Ordina crescente i tag SemVer validi; ignora silenziosamente gli altri."""
    parsed = [(parse(t), t) for t in tags]
    valid = [(key, t) for key, t in parsed if key is not None]
    valid.sort(key=lambda item: item[0])
    return [t for _, t in valid]


def latest(tags: list[str]) -> str | None:
    ordered = sort_tags(tags)
    return ordered[-1] if ordered else None


def tags_after(tags: list[str], baseline: str | None) -> list[str]:
    """Tag SemVer strettamente successivi a `baseline`, in ordine crescente.

    Se `baseline` e' None (o non SemVer), restituisce tutti i tag validi.
    """
    ordered = sort_tags(tags)
    baseline_key = parse(baseline) if baseline else None
    if baseline_key is None:
        return ordered
    return [t for t in ordered if (key := parse(t)) is not None and key > baseline_key]
