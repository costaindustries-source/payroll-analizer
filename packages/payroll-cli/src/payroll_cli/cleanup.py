"""Scansione e rimozione di residui locali: work/ (area temporanea OCR),
logs/ oltre retention, backups/ oltre il numero da conservare.

Le immagini Docker dangling sono solo riportate, mai rimosse da qui: una
volta superate perdono il tag del progetto, quindi non c'e' modo affidabile
di distinguerle da quelle di un altro progetto sullo stesso host (v.
docs/CLI_REDESIGN_PROPOSAL.md §2, principio di sicurezza sulle risorse
condivise). Rimozione manuale: `docker image prune`.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from payroll_cli.context import MachineConfig

_BACKUP_GLOB = "payroll_*.dump"
_DEFAULT_LOGS_RETENTION_DAYS = 90
_DEFAULT_BACKUPS_KEEP = 5


@dataclass
class CleanupItem:
    path: Path
    reason: str
    size_bytes: int
    extra_paths: list[Path] = field(default_factory=list)


@dataclass
class CleanupReport:
    work_residuals: list[CleanupItem] = field(default_factory=list)
    old_logs: list[CleanupItem] = field(default_factory=list)
    old_backups: list[CleanupItem] = field(default_factory=list)
    dangling_images_count: int = 0
    dangling_images_size_bytes: int = 0

    @property
    def filesystem_items(self) -> list[CleanupItem]:
        return [*self.work_residuals, *self.old_logs, *self.old_backups]


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def scan(repo_root: Path, machine: MachineConfig | None) -> CleanupReport:
    retention_days = machine.logs_retention_days if machine else _DEFAULT_LOGS_RETENTION_DAYS
    keep_backups = machine.backups_keep if machine else _DEFAULT_BACKUPS_KEEP

    report = CleanupReport()

    work_dir = repo_root / "work"
    if work_dir.is_dir():
        for p in sorted(work_dir.iterdir()):
            if p.name == ".gitkeep":
                continue
            report.work_residuals.append(CleanupItem(p, "residuo in work/ (area temporanea OCR)", _size(p)))

    logs_dir = repo_root / "logs"
    if logs_dir.is_dir():
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        for p in sorted(logs_dir.iterdir()):
            if p.name == ".gitkeep" or not p.is_file():
                continue
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                report.old_logs.append(CleanupItem(p, f"oltre retention di {retention_days} giorni", _size(p)))

    backups_dir = repo_root / "backups"
    if backups_dir.is_dir():
        dumps = sorted(backups_dir.glob(_BACKUP_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in dumps[keep_backups:]:
            counts_file = p.with_suffix(p.suffix + ".counts")
            extra = [counts_file] if counts_file.is_file() else []
            size = _size(p) + sum(_size(e) for e in extra)
            report.old_backups.append(
                CleanupItem(p, f"oltre gli ultimi {keep_backups} backup conservati", size, extra_paths=extra)
            )

    _scan_dangling_images(report)
    return report


def _scan_dangling_images(report: CleanupReport) -> None:
    ids_result = subprocess.run(
        ["docker", "images", "-f", "dangling=true", "-q"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    ids = [line for line in ids_result.stdout.splitlines() if line]
    report.dangling_images_count = len(ids)
    if not ids:
        return
    size_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Size}}", *ids],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    report.dangling_images_size_bytes = sum(int(s) for s in size_result.stdout.split() if s.isdigit())


def apply(report: CleanupReport, log=print) -> None:
    """Rimuove SOLO gli item su filesystem del report; le immagini dangling
    non sono mai toccate qui (v. docstring del modulo)."""
    for item in report.filesystem_items:
        if item.path.is_dir():
            shutil.rmtree(item.path)
        else:
            item.path.unlink(missing_ok=True)
        for extra in item.extra_paths:
            extra.unlink(missing_ok=True)
        log(f"Rimosso: {item.path}")
