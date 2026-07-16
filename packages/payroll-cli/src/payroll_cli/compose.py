"""Wrapper minimi su `docker compose`, eseguiti sempre con cwd=repo_root
(cosi' il comando trova il docker-compose.yml del progetto indipendentemente
dalla directory da cui e' stato invocato `payroll`)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path


def _run(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    # stdin=DEVNULL: nessuno di questi comandi e' interattivo. Senza, erediterebbe
    # lo stdin reale del processo padre — se un chiamante concatena una di queste
    # probe (es. db_env per leggere le credenziali) prima di una vera sessione
    # interattiva (v. exec_in_db_interactive), la probe intercetterebbe/consumerebbe
    # l'input destinato alla sessione successiva sullo stesso stdin ereditato.
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
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


def up_db(repo_root: Path) -> subprocess.CompletedProcess:
    return _run(repo_root, ["up", "-d", "db"])


def build_app(repo_root: Path) -> subprocess.CompletedProcess:
    return _run(repo_root, ["build", "app"])


def app_image_created_at(repo_root: Path) -> datetime | None:
    """Timestamp di creazione dell'immagine 'app' gia' buildata (None se non
    esiste ancora, o se docker/l'immagine non sono raggiungibili): usato per
    avvisare quando il codice in packages/ e' piu' recente della build (GH #26,
    'docker compose run' riusa l'immagine stale senza avviso)."""
    images = _run(repo_root, ["images", "app", "--format", "json"])
    if images.returncode != 0 or not images.stdout.strip():
        return None
    try:
        payload = json.loads(images.stdout)
    except json.JSONDecodeError:
        return None

    entries = payload if isinstance(payload, list) else [payload]
    image_name = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        service = entry.get("Service")
        if service not in (None, "app"):
            continue
        repository = entry.get("Repository")
        if not repository or repository == "<none>":
            continue
        tag = entry.get("Tag")
        image_name = f"{repository}:{tag}" if tag and tag != "<none>" else repository
        break

    if images.returncode != 0 or not image_name:
        return None
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.Created}}", image_name],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if inspect.returncode != 0:
        return None
    try:
        return datetime.fromisoformat(inspect.stdout.strip())
    except ValueError:
        return None


def exec_in_db_binary_stdout(repo_root: Path, args: list[str], dest: Path) -> subprocess.CompletedProcess:
    """Come exec_in_db, ma per comandi che scrivono dati binari su stdout
    (es. pg_dump -Fc): text=True corromperebbe l'output."""
    with dest.open("wb") as f:
        return subprocess.run(
            ["docker", "compose", "exec", "-T", "db", *args],
            cwd=repo_root,
            stdout=f,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )


def cp_to_db(repo_root: Path, local_path: Path, container_dest: str) -> subprocess.CompletedProcess:
    return _run(repo_root, ["cp", str(local_path), f"db:{container_dest}"])


def exec_in_db_interactive(repo_root: Path, args: list[str]) -> int:
    """Per comandi interattivi (es. psql): eredita stdio del terminale, nessun
    output catturato. Ritorna il returncode."""
    proc = subprocess.run(["docker", "compose", "exec", "db", *args], cwd=repo_root)
    return proc.returncode
