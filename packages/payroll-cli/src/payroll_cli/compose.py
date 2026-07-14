"""Wrapper minimi su `docker compose`, eseguiti sempre con cwd=repo_root
(cosi' il comando trova il docker-compose.yml del progetto indipendentemente
dalla directory da cui e' stato invocato `payroll`)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )


def ps_status(repo_root: Path, service: str) -> str | None:
    """Status riportato da 'docker compose ps' per un servizio; None se non e' in esecuzione."""
    result = _run(repo_root, ["ps", service, "--format", "{{.Status}}"])
    output = result.stdout.strip()
    return output or None


def exec_in_db(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return _run(repo_root, ["exec", "-T", "db", *args])


def run_in_app(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return _run(repo_root, ["run", "--rm", "app", *args])


def db_env(repo_root: Path, var: str) -> str | None:
    result = exec_in_db(repo_root, ["printenv", var])
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def db_is_running(repo_root: Path) -> bool:
    status = ps_status(repo_root, "db")
    return status is not None and "up" in status.lower()
