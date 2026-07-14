"""Deploy key SSH read-only per l'autenticazione dei nodi verso GitHub
(v. docs/CLI_REDESIGN_PROPOSAL.md §7, §10.1 — decisione: deploy key SSH).

Una macchina 'node' non deve avere credenziali con permesso di scrittura sul
repo: la chiave e' generata localmente, la parte privata non lascia mai la
macchina — solo la pubblica va autorizzata a mano su GitHub (Settings del
repo -> Deploy keys -> Add deploy key, SENZA spuntare 'Allow write access').
Read-only per costruzione, revocabile per singola macchina senza toccare le
altre. core.sshCommand e' impostato con 'git config --local', quindi vale
SOLO per questo repo: non tocca ~/.ssh/config ne' altri repo sulla stessa
macchina.
"""

from __future__ import annotations

import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_KEY_PATH = Path.home() / ".ssh" / "payroll-deploy"
_HTTPS_GITHUB_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")


class DeployKeyError(RuntimeError):
    pass


@dataclass
class DeployKeyStatus:
    private_key: Path
    public_key: Path
    generated: bool
    public_key_content: str


def ensure_deploy_key(key_path: Path | None = None, comment: str | None = None) -> DeployKeyStatus:
    key_path = key_path or _DEFAULT_KEY_PATH
    pub_path = Path(str(key_path) + ".pub")

    if key_path.is_file() and pub_path.is_file():
        return DeployKeyStatus(
            key_path, pub_path, generated=False, public_key_content=pub_path.read_text(encoding="utf-8").strip()
        )

    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    comment = comment or f"payroll-analizer-deploy@{socket.gethostname()}"
    result = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-C", comment],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise DeployKeyError(f"ssh-keygen fallito: {result.stderr.strip()}")
    key_path.chmod(0o600)
    return DeployKeyStatus(
        key_path, pub_path, generated=True, public_key_content=pub_path.read_text(encoding="utf-8").strip()
    )


def get_remote_url(repo_root: Path, remote: str = "origin") -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", remote], cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if result.returncode != 0:
        raise DeployKeyError(f"Remote '{remote}' non trovato: {result.stderr.strip()}")
    return result.stdout.strip()


def https_to_ssh_url(url: str) -> str | None:
    """None se l'URL non e' un HTTPS github.com riconoscibile (es. gia' SSH)."""
    match = _HTTPS_GITHUB_RE.match(url)
    if not match:
        return None
    owner, repo = match.groups()
    return f"git@github.com:{owner}/{repo}.git"


def set_remote_url(repo_root: Path, remote: str, url: str) -> None:
    result = subprocess.run(
        ["git", "remote", "set-url", remote, url], cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if result.returncode != 0:
        raise DeployKeyError(f"Impossibile aggiornare remote '{remote}': {result.stderr.strip()}")


def configure_ssh_command(repo_root: Path, key_path: Path) -> None:
    ssh_command = f"ssh -i {key_path} -o IdentitiesOnly=yes"
    result = subprocess.run(
        ["git", "config", "--local", "core.sshCommand", ssh_command],
        cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise DeployKeyError(f"Impossibile impostare core.sshCommand: {result.stderr.strip()}")
