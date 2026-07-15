"""Test di payroll_cli.commands.db (db_app): backup/restore/migrate/shell.
db_app e' un typer.Typer autonomo (montato da main.py sotto 'db'): qui lo si
monta su un piccolo Typer 'root' di comodo che imposta ctx.obj, per isolarlo
da main.py (che ha il proprio test in test_main.py). Il modulo payroll_cli.db
e' mockato: nessun docker/postgres reale viene invocato."""

from __future__ import annotations

from pathlib import Path

import typer
from typer.testing import CliRunner

from payroll_cli import db as db_module
from payroll_cli.commands.db import db_app
from payroll_cli.context import Context

runner = CliRunner()


def _root_app(ctx_obj: Context) -> typer.Typer:
    root = typer.Typer()

    @root.callback()
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = ctx_obj

    root.add_typer(db_app, name="db")
    return root


def _ctx(tmp_path):
    return Context(repo_root=tmp_path, machine=None)


# --- backup ---


def test_backup_success_prints_summary(monkeypatch, tmp_path):
    result_obj = db_module.BackupResult(
        dump_path=tmp_path / "payroll_x.dump", counts_path=tmp_path / "payroll_x.dump.counts", table_count=7
    )
    monkeypatch.setattr(db_module, "backup", lambda repo_root, backups_dir=None, log=print: result_obj)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "backup"])
    assert result.exit_code == 0
    assert f"Backup: {result_obj.dump_path} (7 tabelle)" in result.output


def test_backup_forwards_output_option(monkeypatch, tmp_path):
    captured = {}

    def fake_backup(repo_root, backups_dir=None, log=print):
        captured["backups_dir"] = backups_dir
        return db_module.BackupResult(dump_path=tmp_path / "d.dump", counts_path=tmp_path / "d.dump.counts", table_count=1)

    monkeypatch.setattr(db_module, "backup", fake_backup)
    custom_dir = tmp_path / "custom-backups"
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "backup", "--output", str(custom_dir)])
    assert result.exit_code == 0
    assert captured["backups_dir"] == custom_dir


def test_backup_db_error_exits_1(monkeypatch, tmp_path):
    def fake_backup(repo_root, backups_dir=None, log=print):
        raise db_module.DbError("dump fallito")

    monkeypatch.setattr(db_module, "backup", fake_backup)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "backup"])
    assert result.exit_code == 1
    assert "ERRORE: dump fallito" in result.output


# --- restore ---


def test_restore_performed_prints_completion_and_volume_warning(monkeypatch, tmp_path):
    dump = tmp_path / "payroll_x.dump"
    monkeypatch.setattr(
        db_module,
        "restore",
        lambda repo_root, dump_path=None, log=print: db_module.RestoreResult(
            performed=True, dump_path=dump, mismatches=[]
        ),
    )
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "restore"])
    assert result.exit_code == 0
    assert f"Restore completato da {dump}." in result.output
    assert "docker volume rm" in result.output


def test_restore_noop_prints_nothing_extra(monkeypatch, tmp_path):
    monkeypatch.setattr(
        db_module,
        "restore",
        lambda repo_root, dump_path=None, log=print: db_module.RestoreResult(
            performed=False, dump_path=None, mismatches=[]
        ),
    )
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "restore"])
    assert result.exit_code == 0
    assert "Restore completato" not in result.output


def test_restore_forwards_dump_argument(monkeypatch, tmp_path):
    captured = {}
    dump = tmp_path / "explicit.dump"
    dump.write_bytes(b"x")

    def fake_restore(repo_root, dump_path=None, log=print):
        captured["dump_path"] = dump_path
        return db_module.RestoreResult(performed=True, dump_path=dump_path, mismatches=[])

    monkeypatch.setattr(db_module, "restore", fake_restore)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "restore", str(dump)])
    assert result.exit_code == 0
    assert captured["dump_path"] == dump


def test_restore_db_error_exits_1(monkeypatch, tmp_path):
    def fake_restore(repo_root, dump_path=None, log=print):
        raise db_module.DbError("conteggi non corrispondenti")

    monkeypatch.setattr(db_module, "restore", fake_restore)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "restore"])
    assert result.exit_code == 1
    assert "ERRORE: conteggi non corrispondenti" in result.output


# --- migrate ---


def test_migrate_default_revision_head(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(db_module, "migrate", lambda repo_root, revision="head": captured.setdefault("revision", revision))
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "migrate"])
    assert result.exit_code == 0
    assert captured["revision"] == "head"
    assert "Migration applicate fino a: head" in result.output


def test_migrate_explicit_revision(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(db_module, "migrate", lambda repo_root, revision="head": captured.setdefault("revision", revision))
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "migrate", "0007"])
    assert result.exit_code == 0
    assert captured["revision"] == "0007"
    assert "Migration applicate fino a: 0007" in result.output


def test_migrate_db_error_exits_1(monkeypatch, tmp_path):
    def fake_migrate(repo_root, revision="head"):
        raise db_module.DbError("alembic upgrade fallito")

    monkeypatch.setattr(db_module, "migrate", fake_migrate)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "migrate"])
    assert result.exit_code == 1
    assert "ERRORE: alembic upgrade fallito" in result.output


# --- shell ---


def test_shell_success_exit_0(monkeypatch, tmp_path):
    monkeypatch.setattr(db_module, "shell", lambda repo_root: 0)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "shell"])
    assert result.exit_code == 0


def test_shell_nonzero_returncode_propagates_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(db_module, "shell", lambda repo_root: 3)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["db", "shell"])
    assert result.exit_code == 3
