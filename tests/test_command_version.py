"""Test di payroll_cli.commands.version.run(): tutte le sue ramificazioni
(versione pacchetto installata/non installata, tag/nearest-tag, dirty, db
raggiungibile o meno, esiti alembic). git_ops e compose sono mockati."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace

from payroll_cli import compose as compose_module
from payroll_cli.commands import version as version_cmd
from payroll_cli.context import Context, MachineConfig


def _ctx(tmp_path, machine=None):
    return Context(repo_root=tmp_path, machine=machine)


def _raise_package_not_found(name):
    raise PackageNotFoundError()


def _patch_git(monkeypatch, *, tag=None, nearest=None, branch="main", commit="abc123", dirty=False):
    monkeypatch.setattr(version_cmd.git_ops, "exact_tag_on_head", lambda repo_root: tag)
    monkeypatch.setattr(version_cmd.git_ops, "nearest_tag", lambda repo_root: nearest)
    monkeypatch.setattr(version_cmd.git_ops, "current_branch", lambda repo_root: branch)
    monkeypatch.setattr(version_cmd.git_ops, "current_commit", lambda repo_root: commit)
    monkeypatch.setattr(version_cmd.git_ops, "is_dirty", lambda repo_root: dirty)


def test_cli_version_dev_fallback_when_package_not_installed(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", _raise_package_not_found)
    _patch_git(monkeypatch, tag="v1.0.0")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: False)
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "payroll-cli: dev" in out


def test_cli_version_from_installed_package(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.2.3")
    _patch_git(monkeypatch, tag="v1.0.0")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: False)
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "payroll-cli: 1.2.3" in out


def test_head_on_tag_with_dirty_worktree(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag="v1.0.0", branch="main", commit="deadbee", dirty=True)
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: False)
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "repo: v1.0.0 (main@deadbee) (modifiche non committate)" in out


def test_head_not_on_tag_but_nearest_known(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag=None, nearest="v0.9.0", branch="feature/x", commit="cafebee")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: False)
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "repo: feature/x@cafebee da v0.9.0 (HEAD non e' su un tag)" in out


def test_head_not_on_tag_and_no_nearest(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag=None, nearest=None, branch="main", commit="cafebee")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: False)
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "repo: main@cafebee (HEAD non e' su un tag)" in out


def test_machine_not_configured(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag="v1.0.0")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: False)
    version_cmd.run(_ctx(tmp_path, machine=None))
    out = capsys.readouterr().out
    assert "macchina: non configurata (esegui 'payroll setup')" in out


def test_machine_configured(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag="v1.0.0")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: False)
    version_cmd.run(_ctx(tmp_path, machine=MachineConfig(name="host1", role="node")))
    out = capsys.readouterr().out
    assert "macchina: host1 (ruolo: node)" in out


def test_db_not_running_skips_postgres_and_alembic(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag="v1.0.0")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: False)
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "postgres: container 'db' non in esecuzione" in out
    assert "alembic: sconosciuto (db non raggiungibile)" in out


def test_db_running_reports_pg_version_and_alembic_state(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag="v1.0.0")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: True)
    monkeypatch.setattr(
        version_cmd, "db_env", lambda repo_root, var: {"POSTGRES_USER": "u", "POSTGRES_DB": "d"}[var]
    )
    monkeypatch.setattr(
        compose_module, "exec_in_db", lambda repo_root, args: SimpleNamespace(returncode=0, stdout="16.4\n", stderr="")
    )

    def fake_run_in_app(repo_root, args):
        if args[-1] == "current":
            return SimpleNamespace(stdout="0001_init\n", stderr="", returncode=0)
        return SimpleNamespace(stdout="0002_head\n", stderr="", returncode=0)

    monkeypatch.setattr(version_cmd, "run_in_app", fake_run_in_app)
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "postgres: 16.4" in out
    assert "alembic current: 0001_init" in out
    assert "alembic head:    0002_head" in out


def test_alembic_empty_output_uses_defaults(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag="v1.0.0")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: True)
    monkeypatch.setattr(version_cmd, "db_env", lambda repo_root, var: "payroll")
    monkeypatch.setattr(
        compose_module, "exec_in_db", lambda repo_root, args: SimpleNamespace(returncode=0, stdout="16.4", stderr="")
    )
    monkeypatch.setattr(
        version_cmd, "run_in_app", lambda repo_root, args: SimpleNamespace(stdout="", stderr="", returncode=0)
    )
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "alembic current: (nessuna revisione applicata)" in out
    assert "alembic head:    (sconosciuto)" in out


def test_pg_version_query_failure_reports_unknown(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(version_cmd, "pkg_version", lambda name: "1.0.0")
    _patch_git(monkeypatch, tag="v1.0.0")
    monkeypatch.setattr(version_cmd, "db_is_running", lambda repo_root: True)
    monkeypatch.setattr(version_cmd, "db_env", lambda repo_root, var: None)
    monkeypatch.setattr(
        compose_module, "exec_in_db", lambda repo_root, args: SimpleNamespace(returncode=1, stdout="", stderr="err")
    )
    monkeypatch.setattr(
        version_cmd, "run_in_app", lambda repo_root, args: SimpleNamespace(stdout="", stderr="", returncode=0)
    )
    version_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "postgres: sconosciuta" in out
