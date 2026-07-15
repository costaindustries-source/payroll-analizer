"""Test dell'entrypoint `payroll` (main.py): callback che risolve repo_root/machine
in ctx.obj, comando 'rollback' e comando 'help' (drilling nell'albero dei comandi).

I moduli sottostanti (context, git_ops, updater, comandi) sono mockati: qui si
verifica solo il cablaggio della CLI, non la logica di business (gia' testata
altrove, e i moduli 'orchestrazione' sono testati da altri gruppi)."""

from __future__ import annotations

from typer.testing import CliRunner

from payroll_cli import context as context_module
from payroll_cli import git_ops, updater
from payroll_cli.commands import cleanup as cleanup_cmd
from payroll_cli.commands import setup as setup_cmd
from payroll_cli.commands import status as status_cmd
from payroll_cli.commands import version as version_cmd
from payroll_cli.context import MachineConfig
from payroll_cli.main import app

runner = CliRunner()


def _ok_context(monkeypatch, tmp_path, machine=None):
    """Fa risolvere con successo il callback di `app` (repo_root/machine)."""
    monkeypatch.setattr(context_module, "find_repo_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(context_module, "load_machine_config", lambda repo_root: machine)


# --- callback: risoluzione repo_root/machine ---


def test_callback_repo_not_found_exits_1(monkeypatch):
    def _raise(*a, **kw):
        raise context_module.RepoNotFoundError("repo mancante da qualche parte")

    monkeypatch.setattr(context_module, "find_repo_root", _raise)
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 1
    assert "repo mancante da qualche parte" in result.output


def test_callback_invalid_machine_config_exits_1(monkeypatch, tmp_path):
    monkeypatch.setattr(context_module, "find_repo_root", lambda *a, **kw: tmp_path)

    def _raise(repo_root):
        raise context_module.InvalidMachineConfigError("config rotta")

    monkeypatch.setattr(context_module, "load_machine_config", _raise)
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 1
    assert "config rotta" in result.output


def test_callback_happy_path_builds_ctx_obj(monkeypatch, tmp_path):
    machine = MachineConfig(name="host1", role="node")
    _ok_context(monkeypatch, tmp_path, machine)
    captured = {}

    def fake_run(ctx_obj):
        captured["ctx"] = ctx_obj

    monkeypatch.setattr(version_cmd, "run", fake_run)
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert captured["ctx"].repo_root == tmp_path
    assert captured["ctx"].machine is machine


def test_status_command_delegates_to_status_cmd(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(status_cmd, "run", lambda ctx_obj: captured.setdefault("ctx", ctx_obj))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert captured["ctx"].repo_root == tmp_path


def test_cleanup_command_delegates_with_apply_flag(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(
        cleanup_cmd, "run", lambda ctx_obj, apply_changes: captured.update(ctx=ctx_obj, apply_changes=apply_changes)
    )
    result = runner.invoke(app, ["cleanup", "--apply"])
    assert result.exit_code == 0
    assert captured["apply_changes"] is True


def test_setup_command_delegates_all_options(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    captured = {}

    def fake_run(ctx_obj, **kwargs):
        captured["ctx"] = ctx_obj
        captured.update(kwargs)

    monkeypatch.setattr(setup_cmd, "run", fake_run)
    result = runner.invoke(app, ["setup", "--check", "--name", "host1", "--role", "node"])
    assert result.exit_code == 0
    assert captured["check_only"] is True
    assert captured["name"] == "host1"
    assert captured["role"] == "node"


# --- comando rollback ---


def test_rollback_tag_not_found_locally(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: [])
    result = runner.invoke(app, ["rollback", "v9.9.9"])
    assert result.exit_code == 1
    assert "non trovato localmente" in result.output


def test_rollback_declined_by_user(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.0.0"])
    result = runner.invoke(app, ["rollback", "v1.0.0"], input="n\n")
    assert result.exit_code == 0
    assert "Interrotto su richiesta." in result.output


def test_rollback_success(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.0.0"])
    called = {}

    def fake_rollback(repo_root, tag, log):
        called["tag"] = tag
        log("rollback in corso")

    monkeypatch.setattr(updater, "do_rollback", fake_rollback)
    result = runner.invoke(app, ["rollback", "v1.0.0"], input="y\n")
    assert result.exit_code == 0
    assert called["tag"] == "v1.0.0"
    assert "Rollback a v1.0.0 completato." in result.output


def test_rollback_update_error_exits_1(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.0.0"])

    def fake_rollback(repo_root, tag, log):
        raise updater.UpdateError("boom")

    monkeypatch.setattr(updater, "do_rollback", fake_rollback)
    result = runner.invoke(app, ["rollback", "v1.0.0"], input="y\n")
    assert result.exit_code == 1
    assert "ERRORE: boom" in result.output


# --- comando help (drilling nell'albero comandi/sottocomandi) ---


def test_help_root(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "CLI operativa per payroll-analizer" in result.output


def test_help_specific_command(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    result = runner.invoke(app, ["help", "version"])
    assert result.exit_code == 0
    assert "Versione CLI" in result.output


def test_help_unknown_command(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    result = runner.invoke(app, ["help", "nope"])
    assert result.exit_code == 1
    assert "Comando sconosciuto" in result.output


def test_help_drill_into_leaf_command_errors(monkeypatch, tmp_path):
    """'version' non e' un gruppo: chiedere l'help di un suo sotto-comando deve fallire."""
    _ok_context(monkeypatch, tmp_path)
    result = runner.invoke(app, ["help", "version", "extra"])
    assert result.exit_code == 1
    assert "'extra' non e' un gruppo di comandi." in result.output


def test_help_nested_group_command(monkeypatch, tmp_path):
    _ok_context(monkeypatch, tmp_path)
    result = runner.invoke(app, ["help", "db", "backup"])
    assert result.exit_code == 0
    assert "Dump completo" in result.output
