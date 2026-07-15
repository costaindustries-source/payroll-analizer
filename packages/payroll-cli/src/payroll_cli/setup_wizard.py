"""Scrittura della configurazione per-macchina e bootstrap iniziale
(build immagine, avvio db, migration, smoke test)."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import tomli_w

from payroll_cli import compose
from payroll_cli import db as db_module
from payroll_cli.context import MachineConfig

_DEFAULT_DB_PORT = 5432


def default_machine_name() -> str:
    return socket.gethostname()


def write_config(repo_root: Path, config: MachineConfig) -> Path:
    path = repo_root / "payroll.local.toml"
    data = {
        "machine": {"name": config.name, "role": config.role},
        "db": {"host_port": config.db_host_port},
        "update": {"auto_backup": config.auto_backup},
        "cleanup": {
            "logs_retention_days": config.logs_retention_days,
            "backups_keep": config.backups_keep,
        },
    }
    path.write_text(tomli_w.dumps(data), encoding="utf-8")
    return path


def maybe_write_override(repo_root: Path, db_host_port: int, log=print) -> Path | None:
    """Genera docker-compose.override.yml SOLO se la porta scelta differisce
    dal default (5432) e SOLO se il file non esiste gia' (non sovrascrive mai
    una personalizzazione manuale esistente — v. docs/RELEASE_PROCESS.md,
    'Configurazione specifica per ambiente')."""
    override_path = repo_root / "docker-compose.override.yml"
    if db_host_port == _DEFAULT_DB_PORT:
        return None
    if override_path.is_file():
        log(f"{override_path} esiste gia': non sovrascritto (verifica a mano che la porta combaci).")
        return override_path
    # "!override" e' necessario: docker compose concatena le liste (ports,
    # volumes, ...) tra file invece di sostituirle, quindi senza questo tag
    # il bind della 5432 di default resterebbe attivo insieme a questo e
    # fallirebbe se la 5432 e' occupata (v. issue #14).
    content = "services:\n  db:\n    ports: !override\n" f'      - "127.0.0.1:{db_host_port}:5432"\n'
    override_path.write_text(content, encoding="utf-8")
    log(f"Generato {override_path} (porta host DB: {db_host_port}).")
    return override_path


class BootstrapError(RuntimeError):
    pass


def bootstrap(repo_root: Path, log=print) -> None:
    """Sequenza idempotente: build immagine, avvio db, migration, smoke test
    (se i campioni locali in docs/payroll-test/ sono disponibili)."""
    log("== Build immagine 'app' ==")
    result = compose.build_app(repo_root)
    if result.returncode != 0:
        raise BootstrapError(f"Build fallita: {result.stderr.strip()}")

    log("== Avvio 'db' ==")
    compose.up_db(repo_root)
    db_module.wait_db_healthy(repo_root)

    log("== Migration Alembic ==")
    db_module.migrate(repo_root)

    samples_dir = repo_root / "docs" / "payroll-test"
    if samples_dir.is_dir() and any(samples_dir.glob("*.pdf")):
        log("== Smoke test (campioni locali) ==")
        result = subprocess.run(
            ["uv", "run", "python", "scripts/smoke_test.py"],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise BootstrapError("Smoke test fallito.")
    else:
        log("Nessun campione in docs/payroll-test/: smoke test saltato.")
