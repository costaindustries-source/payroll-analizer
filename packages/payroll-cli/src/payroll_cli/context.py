"""Discovery del repository e lettura della configurazione per-macchina.

`payroll` gira sull'host (non nel container): deve risalire da solo alla
radice del checkout payroll-analizer, perche' l'operatore lo invoca da
qualunque directory dentro (o vicino a) il repo.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

_COMPOSE_MARKER = "docker-compose.yml"
_WORKSPACE_MARKER = "packages/payroll-cli/pyproject.toml"
_LOCAL_CONFIG_NAME = "payroll.local.toml"


class RepoNotFoundError(RuntimeError):
    pass


class InvalidMachineConfigError(RuntimeError):
    pass


_VALID_ROLES = {"source", "node"}
_MIN_PORT = 1
_MAX_PORT = 65535


def find_repo_root(start: Path | None = None) -> Path:
    """Risale da `start` (default: cwd) fino a trovare la radice del repo.

    Rispetta PAYROLL_REPO_ROOT se impostata (utile per test o layout non
    standard), altrimenti cerca la prima directory che contiene sia
    docker-compose.yml sia il pyproject.toml di questo stesso pacchetto
    (cosi' non e' confusa da un docker-compose.yml di un altro progetto).
    """
    env_override = os.environ.get("PAYROLL_REPO_ROOT")
    if env_override:
        root = Path(env_override).expanduser().resolve()
        if not (root / _COMPOSE_MARKER).is_file():
            raise RepoNotFoundError(f"PAYROLL_REPO_ROOT={root} non contiene {_COMPOSE_MARKER}.")
        return root

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / _COMPOSE_MARKER).is_file() and (candidate / _WORKSPACE_MARKER).is_file():
            return candidate
    raise RepoNotFoundError(
        f"Repository payroll-analizer non trovato risalendo da {current}. "
        "Esegui 'payroll' da dentro il checkout, oppure imposta PAYROLL_REPO_ROOT."
    )


@dataclass
class MachineConfig:
    name: str
    role: str  # "source" (solo Ubuntu/dev) | "node" (macchina installata)
    db_host_port: int = 5432
    auto_backup: bool = True
    logs_retention_days: int = 90
    backups_keep: int = 5

    @property
    def is_source(self) -> bool:
        return self.role == "source"


def load_machine_config(repo_root: Path) -> MachineConfig | None:
    """None se la macchina non e' ancora stata configurata (`payroll setup`).

    `payroll.local.toml` e' scritto esclusivamente da `payroll setup` (non
    versionato): le validazioni sotto servono solo a dare un errore chiaro se
    il file viene modificato a mano in modo malformato, invece di propagare un
    valore silenziosamente sbagliato a valle (es. in `docker compose`/confronti
    di stringa) - v. issue GH #23.
    """
    config_path = repo_root / _LOCAL_CONFIG_NAME
    if not config_path.is_file():
        return None
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    machine = data.get("machine", {})
    db = data.get("db", {})
    update = data.get("update", {})
    cleanup = data.get("cleanup", {})

    role = machine.get("role", "node")
    if role not in _VALID_ROLES:
        raise InvalidMachineConfigError(
            f"{config_path}: [machine].role={role!r} non valido, atteso uno tra {sorted(_VALID_ROLES)}."
        )
    db_host_port = db.get("host_port", 5432)
    if isinstance(db_host_port, bool) or not isinstance(db_host_port, int) or not (
        _MIN_PORT <= db_host_port <= _MAX_PORT
    ):
        raise InvalidMachineConfigError(
            f"{config_path}: [db].host_port={db_host_port!r} non valido, atteso un intero tra {_MIN_PORT} e {_MAX_PORT}."
        )

    return MachineConfig(
        name=machine.get("name", "senza-nome"),
        role=role,
        db_host_port=db_host_port,
        auto_backup=update.get("auto_backup", True),
        logs_retention_days=cleanup.get("logs_retention_days", 90),
        backups_keep=cleanup.get("backups_keep", 5),
    )


@dataclass
class Context:
    repo_root: Path
    machine: MachineConfig | None

    @property
    def local_config_path(self) -> Path:
        return self.repo_root / _LOCAL_CONFIG_NAME
