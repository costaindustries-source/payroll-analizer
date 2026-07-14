"""Logica di 'payroll update apply' e 'payroll rollback'.

Modello pull (v. docs/CLI_REDESIGN_PROPOSAL.md §6): il checkout locale si
aggiorna da solo a un tag SemVer, con backup automatico di Postgres se il
bump cambia il nome del volume dati, e un resume post-checkout eseguito dal
codice DEL TAG DI DESTINAZIONE (non da quello ancora in memoria in questo
processo) cosi' un'eventuale correzione alla logica di restore/migrate nel
nuovo tag si applica gia' al proprio stesso aggiornamento.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from payroll_cli import compose, git_ops, semver
from payroll_cli import db as db_module

_VOLUME_LINE_RE = re.compile(r"^\s*-\s*(\S+):/var/lib/postgresql/data\s*$", re.MULTILINE)
_SAMPLES_DIR = ("docs", "payroll-test")


class UpdateError(RuntimeError):
    pass


def resolve_target(repo_root: Path, to_tag: str | None) -> str:
    local_tags = git_ops.list_local_tags(repo_root)
    if to_tag:
        if to_tag not in local_tags:
            raise UpdateError(f"Tag '{to_tag}' non trovato localmente (esegui prima 'payroll update check').")
        return to_tag
    latest = semver.latest(local_tags)
    if latest is None:
        raise UpdateError("Nessun tag SemVer trovato localmente.")
    return latest


def _pg_volume_name(repo_root: Path, ref: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:docker-compose.yml"],
        cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return None
    match = _VOLUME_LINE_RE.search(result.stdout)
    return match.group(1) if match else None


def pg_volume_changed(repo_root: Path, from_ref: str, to_ref: str) -> bool:
    """True se il nome del volume dati Postgres cambia tra le due ref (bump
    di major version, v. upgrade-postgres.sh). Se una delle due ref non e'
    leggibile, assume che sia cambiato: un backup di troppo e' innocuo, un
    backup saltato quando serviva no."""
    current = _pg_volume_name(repo_root, from_ref)
    target = _pg_volume_name(repo_root, to_ref)
    if current is None or target is None:
        return True
    return current != target


def ensure_clean_worktree(repo_root: Path) -> None:
    if git_ops.is_dirty(repo_root):
        raise UpdateError(
            "Working tree non pulito: committa o stash prima di aggiornare "
            "(mai fatto un checkout su modifiche non salvate)."
        )


def checkout(repo_root: Path, tag: str) -> None:
    result = subprocess.run(
        ["git", "checkout", "-q", tag], cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if result.returncode != 0:
        raise UpdateError(f"Checkout di {tag} fallito: {result.stderr.strip()}")


def _run_smoke_test(repo_root: Path, log) -> None:
    samples_dir = repo_root.joinpath(*_SAMPLES_DIR)
    if not (samples_dir.is_dir() and any(samples_dir.glob("*.pdf"))):
        log("Nessun campione in docs/payroll-test/: smoke test saltato.")
        return
    log("== Smoke test ==")
    result = subprocess.run(
        ["uv", "run", "python", "scripts/smoke_test.py"], cwd=repo_root, stdin=subprocess.DEVNULL
    )
    if result.returncode != 0:
        raise UpdateError("Smoke test fallito dopo l'aggiornamento.")


def resume(repo_root: Path, log=print) -> None:
    """Eseguito DOPO il checkout, dal codice del tag di destinazione (via
    reexec_resume): build immagine, avvio db, restore (no-op se il volume
    non era cambiato), migration, smoke test."""
    log("== Build immagine 'app' ==")
    result = compose.build_app(repo_root)
    if result.returncode != 0:
        raise UpdateError(f"Build fallita: {result.stderr.strip()}")

    log("== Avvio 'db' ==")
    compose.up_db(repo_root)
    db_module.wait_db_healthy(repo_root)

    log("== Restore (no-op se il volume non e' cambiato) ==")
    try:
        restore_result = db_module.restore(repo_root, log=log)
    except db_module.DbError as exc:
        raise UpdateError(str(exc)) from exc
    if restore_result.performed:
        log(f"Dati ripristinati da {restore_result.dump_path}.")

    log("== Migration Alembic ==")
    try:
        db_module.migrate(repo_root)
    except db_module.DbError as exc:
        raise UpdateError(str(exc)) from exc

    _run_smoke_test(repo_root, log)


def reexec_resume(repo_root: Path, previous_tag: str | None) -> int:
    """Rilancia 'payroll update apply --resume' dal checkout AGGIORNATO:
    cosi' backup/restore/migrate girano con la logica del tag appena
    installato, non con quella vecchia ancora in memoria in questo processo."""
    args = ["uv", "run", "payroll", "update", "apply", "--resume"]
    if previous_tag:
        args += ["--previous-tag", previous_tag]
    result = subprocess.run(args, cwd=repo_root)
    return result.returncode


def log_update(repo_root: Path, from_tag: str | None, to_tag: str, outcome: str) -> None:
    """Traccia locale (non versionata) degli aggiornamenti eseguiti su questa macchina."""
    logs_dir = repo_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{timestamp}\t{from_tag or '?'} -> {to_tag}\t{outcome}\n"
    with (logs_dir / "updates.log").open("a", encoding="utf-8") as f:
        f.write(line)


def do_rollback(repo_root: Path, tag: str, log=print) -> None:
    """Checkout + rebuild immagine. Non tocca dati/volumi (nessun restore
    automatico: il rollback e' un'azione di emergenza, minimizza i passi)."""
    ensure_clean_worktree(repo_root)
    checkout(repo_root, tag)
    log(f"== Rebuild immagine per {tag} ==")
    result = compose.build_app(repo_root)
    if result.returncode != 0:
        raise UpdateError(f"Build fallita durante il rollback: {result.stderr.strip()}")
