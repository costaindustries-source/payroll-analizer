"""Verifica prerequisiti host per 'payroll setup' (read-only, sempre rieseguibile)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_MIN_FREE_GB = 2.0


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    blocking: bool = True


def _tool_version(args: list[str]) -> tuple[bool, str]:
    exe = shutil.which(args[0])
    if not exe:
        return False, f"'{args[0]}' non trovato nel PATH"
    result = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, detail or f"'{' '.join(args)}' ha restituito un errore"
    output = (result.stdout or result.stderr).strip()
    return True, output.splitlines()[0] if output else "OK"


def run_checks(repo_root: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []

    ok, detail = _tool_version(["docker", "--version"])
    checks.append(CheckResult("docker", ok, detail))

    ok, detail = _tool_version(["docker", "compose", "version"])
    checks.append(CheckResult("docker compose", ok, detail))

    ok, detail = _tool_version(["git", "--version"])
    checks.append(CheckResult("git", ok, detail))

    ok, detail = _tool_version(["uv", "--version"])
    checks.append(CheckResult("uv", ok, detail, blocking=False))

    usage = shutil.disk_usage(repo_root)
    free_gb = usage.free / (1024**3)
    checks.append(CheckResult("spazio disco", free_gb >= _MIN_FREE_GB, f"{free_gb:.1f} GiB liberi"))

    # os.getuid()/os.getgid() sono API POSIX, assenti su Windows (v. issue
    # riscontrata avviando 'payroll setup' su Windows nativo): il controllo
    # UID/GID riguarda solo la proprieta' dei file nei bind mount su Linux/WSL,
    # non ha equivalente su Windows, quindi li' va semplicemente saltato
    # invece di far fallire l'intero comando con un AttributeError.
    if hasattr(os, "getuid"):
        uid, gid = os.getuid(), os.getgid()
        uid_ok = uid == 1000 and gid == 1000
        detail = f"{uid}:{gid}"
        if not uid_ok:
            detail += " (atteso 1000:1000 — altrimenti build con --build-arg APP_UID/APP_GID)"
        checks.append(CheckResult("UID/GID host", uid_ok, detail, blocking=False))
    else:
        checks.append(CheckResult("UID/GID host", True, "non applicabile su Windows", blocking=False))

    return checks
