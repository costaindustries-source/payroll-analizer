"""Wrapper minimi su git per la CLI operativa (nessuna dipendenza da GitPython:
un subprocess a comando e' piu' che sufficiente e resta ispezionabile)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _run(repo_root: Path, args: list[str]) -> GitResult:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return GitResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def current_branch(repo_root: Path) -> str:
    return _run(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout


def exact_tag_on_head(repo_root: Path) -> str | None:
    """Tag esatto su HEAD, o None se HEAD non e' su un tag."""
    result = _run(repo_root, ["describe", "--tags", "--exact-match"])
    return result.stdout if result.ok else None


def nearest_tag(repo_root: Path) -> str | None:
    """Tag raggiungibile piu' vicino a HEAD (anche se HEAD lo ha superato)."""
    result = _run(repo_root, ["describe", "--tags", "--abbrev=0"])
    return result.stdout if result.ok else None


def current_commit(repo_root: Path, short: bool = True) -> str:
    args = ["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"]
    return _run(repo_root, args).stdout


def is_dirty(repo_root: Path) -> bool:
    return bool(_run(repo_root, ["status", "--porcelain"]).stdout)


def fetch_tags(repo_root: Path) -> GitResult:
    return _run(repo_root, ["fetch", "--tags", "--force", "origin"])


def list_local_tags(repo_root: Path) -> list[str]:
    result = _run(repo_root, ["tag", "-l"])
    return [line for line in result.stdout.splitlines() if line]


def diff_file_between(repo_root: Path, ref_a: str, ref_b: str, file_path: str) -> str:
    """Diff testuale di un file tra due ref (tag/commit); stringa vuota se identico."""
    result = _run(repo_root, ["diff", f"{ref_a}..{ref_b}", "--", file_path])
    return result.stdout
