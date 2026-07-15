"""Test per la gestione della deploy key SSH in payroll_cli.deploy_key.

Usa sempre key_path/repo espliciti dentro tmp_path: mai ~/.ssh reale ne'
repo/remote reali. La generazione chiave usa ssh-keygen vero (rapido,
verifica il comportamento reale); solo il caso di errore difficile da
riprodurre mocka subprocess.run.
"""

import stat
import subprocess

import pytest

from payroll_cli import deploy_key

_ENV_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def _git(repo_root, *args, check=True):
    return subprocess.run(["git", *_ENV_ARGS, *args], cwd=repo_root, capture_output=True, text=True, check=check)


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "file.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_ensure_deploy_key_generates_new_key(tmp_path):
    key_path = tmp_path / "ssh" / "deploy-key"
    status = deploy_key.ensure_deploy_key(key_path, comment="test-comment")

    assert status.generated is True
    assert status.private_key == key_path
    assert status.public_key == tmp_path / "ssh" / "deploy-key.pub"
    assert key_path.is_file()
    assert status.public_key.is_file()
    assert status.public_key_content.startswith("ssh-ed25519")
    assert "test-comment" in status.public_key_content
    # permessi ristretti sulla chiave privata
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_ensure_deploy_key_reuses_existing_key(tmp_path):
    key_path = tmp_path / "ssh" / "deploy-key"
    first = deploy_key.ensure_deploy_key(key_path)
    assert first.generated is True

    second = deploy_key.ensure_deploy_key(key_path)
    assert second.generated is False
    assert second.public_key_content == first.public_key_content


def test_ensure_deploy_key_default_comment_includes_hostname(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_key.socket, "gethostname", lambda: "my-test-host")
    key_path = tmp_path / "ssh" / "deploy-key"
    status = deploy_key.ensure_deploy_key(key_path)
    assert "my-test-host" in status.public_key_content


def test_ensure_deploy_key_ssh_keygen_failure_raises(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="ssh-keygen: qualcosa e' andato storto")

    monkeypatch.setattr(deploy_key.subprocess, "run", fake_run)
    key_path = tmp_path / "ssh" / "deploy-key"
    with pytest.raises(deploy_key.DeployKeyError, match="ssh-keygen fallito"):
        deploy_key.ensure_deploy_key(key_path)


def test_get_remote_url_success(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "remote", "add", "origin", "https://github.com/acme/payroll-analizer.git")
    assert deploy_key.get_remote_url(repo) == "https://github.com/acme/payroll-analizer.git"


def test_get_remote_url_missing_remote_raises(tmp_path):
    repo = _init_repo(tmp_path)
    with pytest.raises(deploy_key.DeployKeyError, match="non trovato"):
        deploy_key.get_remote_url(repo, remote="origin")


def test_https_to_ssh_url_variants():
    assert deploy_key.https_to_ssh_url("https://github.com/acme/payroll-analizer.git") == (
        "git@github.com:acme/payroll-analizer.git"
    )
    assert deploy_key.https_to_ssh_url("https://github.com/acme/payroll-analizer") == (
        "git@github.com:acme/payroll-analizer.git"
    )
    assert deploy_key.https_to_ssh_url("https://github.com/acme/payroll-analizer/") == (
        "git@github.com:acme/payroll-analizer.git"
    )


def test_https_to_ssh_url_non_matching_returns_none():
    assert deploy_key.https_to_ssh_url("git@github.com:acme/payroll-analizer.git") is None
    assert deploy_key.https_to_ssh_url("https://gitlab.com/acme/payroll-analizer.git") is None
    assert deploy_key.https_to_ssh_url("not-a-url") is None


def test_set_remote_url_success(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "remote", "add", "origin", "https://github.com/acme/payroll-analizer.git")
    deploy_key.set_remote_url(repo, "origin", "git@github.com:acme/payroll-analizer.git")
    assert deploy_key.get_remote_url(repo) == "git@github.com:acme/payroll-analizer.git"


def test_set_remote_url_missing_remote_raises(tmp_path):
    repo = _init_repo(tmp_path)
    with pytest.raises(deploy_key.DeployKeyError, match="Impossibile aggiornare remote"):
        deploy_key.set_remote_url(repo, "origin", "git@github.com:acme/payroll-analizer.git")


def test_configure_ssh_command_writes_local_git_config(tmp_path):
    repo = _init_repo(tmp_path)
    key_path = tmp_path / "ssh" / "deploy-key"
    deploy_key.configure_ssh_command(repo, key_path)

    result = _git(repo, "config", "--local", "--get", "core.sshCommand")
    assert result.stdout.strip() == f"ssh -i {key_path} -o IdentitiesOnly=yes"


def test_configure_ssh_command_failure_raises(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="config error")

    monkeypatch.setattr(deploy_key.subprocess, "run", fake_run)
    with pytest.raises(deploy_key.DeployKeyError, match="Impossibile impostare core.sshCommand"):
        deploy_key.configure_ssh_command(repo, tmp_path / "key")
