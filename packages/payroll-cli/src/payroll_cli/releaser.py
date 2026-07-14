"""Logica di 'payroll release new/list' (v. docs/CLI_REDESIGN_PROPOSAL.md
§6, §8). Modello pull: pubblica solo un tag SemVer su GitHub — non deploya
nulla su nessuna macchina. La promozione e' responsabilita' di ogni nodo con
'payroll update apply'. Riservato alla macchina role=source (Ubuntu/dev)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from payroll_cli import git_ops, semver
from payroll_cli.context import MachineConfig

_UNRELEASED_HEADING = "## [Non rilasciato]"
_NEXT_HEADING_RE = re.compile(r"\n## \[")
_SAMPLES_DIR = ("docs", "payroll-test")


class ReleaseError(RuntimeError):
    pass


def check_role(machine: MachineConfig | None) -> None:
    if machine is None or machine.role != "source":
        raise ReleaseError(
            "'payroll release' e' riservato alla macchina configurata come role=source "
            "(v. 'payroll setup'). Sulle altre macchine usa 'payroll update apply'."
        )


def preflight(repo_root: Path, version: str) -> None:
    if semver.parse(version) is None:
        raise ReleaseError(f"Versione non valida: '{version}' (atteso formato vX.Y.Z).")
    branch = git_ops.current_branch(repo_root)
    if branch != "main":
        raise ReleaseError(f"Sei su '{branch}', non su 'main'.")
    if git_ops.is_dirty(repo_root):
        raise ReleaseError("Working tree non pulito: committa o stash prima di rilasciare.")
    if version in git_ops.list_local_tags(repo_root):
        raise ReleaseError(f"Il tag '{version}' esiste gia'.")


def run_smoke_test(repo_root: Path, log=print) -> None:
    """A differenza di setup/update, qui i campioni sono OBBLIGATORI: un
    rilascio senza regressione verificata non e' un rilascio."""
    samples_dir = repo_root.joinpath(*_SAMPLES_DIR)
    if not (samples_dir.is_dir() and any(samples_dir.glob("*.pdf"))):
        raise ReleaseError(
            f"Campioni di regressione non trovati in {samples_dir}: il rilascio richiede lo smoke test."
        )
    log("== Smoke test locale ==")
    result = subprocess.run(
        ["uv", "run", "python", "scripts/smoke_test.py"], cwd=repo_root, stdin=subprocess.DEVNULL
    )
    if result.returncode != 0:
        raise ReleaseError("Smoke test fallito: rilascio interrotto.")


def promote_changelog(repo_root: Path, version: str, release_date: str | None = None) -> bool:
    """Rinomina '## [Non rilasciato]' in '## [vX.Y.Z] - data' (stesso
    formato usato finora a mano in questo progetto), lasciandone una nuova
    vuota in cima per il prossimo giro. Ritorna False (nessuna modifica) se
    la sezione non aveva contenuto."""
    changelog_path = repo_root / "CHANGELOG.md"
    if not changelog_path.is_file():
        raise ReleaseError("CHANGELOG.md non trovato.")
    text = changelog_path.read_text(encoding="utf-8")
    if _UNRELEASED_HEADING not in text:
        raise ReleaseError(f"Sezione '{_UNRELEASED_HEADING}' non trovata in CHANGELOG.md.")

    start = text.index(_UNRELEASED_HEADING)
    body_start = start + len(_UNRELEASED_HEADING)
    match = _NEXT_HEADING_RE.search(text, body_start)
    section_end = match.start() if match else len(text)
    section_body = text[body_start:section_end]

    if not section_body.strip():
        return False

    release_date = release_date or datetime.now(timezone.utc).date().isoformat()
    new_heading = f"## [{version}] - {release_date}"
    new_text = text[:start] + f"{_UNRELEASED_HEADING}\n\n{new_heading}" + section_body + text[section_end:]
    changelog_path.write_text(new_text, encoding="utf-8")
    return True


def commit_changelog(repo_root: Path, version: str) -> None:
    subprocess.run(
        ["git", "add", "CHANGELOG.md"], cwd=repo_root, check=True, capture_output=True, stdin=subprocess.DEVNULL
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", f"docs: prepara CHANGELOG per rilascio {version}"],
        cwd=repo_root, check=True, capture_output=True, stdin=subprocess.DEVNULL,
    )


def create_tag(repo_root: Path, version: str, message: str) -> None:
    result = subprocess.run(
        ["git", "tag", "-a", version, "-m", message],
        cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise ReleaseError(f"Creazione tag fallita: {result.stderr.strip()}")


def push(repo_root: Path, version: str) -> None:
    """Due push separati (branch poi tag), stesso ordine di scripts/release.sh."""
    for args in (["push", "origin", "main"], ["push", "origin", version]):
        result = subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        if result.returncode != 0:
            raise ReleaseError(f"'git {' '.join(args)}' fallito: {result.stderr.strip()}")


def create_github_release(repo_root: Path, version: str, notes: str, log=print) -> bool:
    """Crea una GitHub Release via 'gh' con le note del changelog. Non
    critico: un fallimento qui (es. 'gh' non autenticato su questa macchina)
    non invalida il tag/push gia' avvenuti, viene solo segnalato."""
    result = subprocess.run(
        ["gh", "release", "create", version, "--title", version, "--notes", notes or "(nessuna voce in CHANGELOG.md)"],
        cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        log(
            "ATTENZIONE: creazione della GitHub Release fallita (tag e push sono comunque "
            f"riusciti): {result.stderr.strip()}"
        )
        return False
    log(f"GitHub Release creata: {result.stdout.strip()}")
    return True


@dataclass
class TagInfo:
    tag: str
    date: str
    subject: str
    pushed: bool


def list_releases(repo_root: Path, fetch: bool = True) -> list[TagInfo]:
    if fetch:
        git_ops.fetch_tags(repo_root)
    local_tags = semver.sort_tags(git_ops.list_local_tags(repo_root))
    remote_tags = set(git_ops.list_remote_tags(repo_root)) if fetch else set()
    return [
        TagInfo(
            tag=tag,
            date=git_ops.tag_date(repo_root, tag),
            subject=git_ops.tag_subject(repo_root, tag),
            pushed=tag in remote_tags,
        )
        for tag in reversed(local_tags)
    ]
