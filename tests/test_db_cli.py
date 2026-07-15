"""Test per payroll_cli.db (backup/restore/migrate/shell del Postgres via
'docker compose exec'). Nome del file volutamente 'test_db_cli' (non
'test_db') per non confliggere con l'omonimo modulo payroll_ingest/db.py
testato da un altro gruppo di lavoro. compose.* e' sempre mockato: nessuna
chiamata docker reale."""

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from payroll_cli import compose, db


def _cp(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _bcp(returncode=0, stderr=b""):
    return SimpleNamespace(returncode=returncode, stderr=stderr)


# --- _db_credentials ---

def test_db_credentials_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "db_env", lambda repo_root, var: {"POSTGRES_USER": "u", "POSTGRES_DB": "d"}[var])
    assert db._db_credentials(tmp_path) == ("u", "d")


def test_db_credentials_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "db_env", lambda repo_root, var: None)
    with pytest.raises(db.DbError):
        db._db_credentials(tmp_path)


# --- wait_db_healthy ---

def test_wait_db_healthy_returns_when_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "ps_status", lambda repo_root, service: "Up 2 minutes (healthy)")
    db.wait_db_healthy(tmp_path, tries=1, interval_seconds=0)  # non deve sollevare


def test_wait_db_healthy_timeout_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "ps_status", lambda repo_root, service: "Up 2 minutes (starting)")
    with pytest.raises(db.DbError):
        db.wait_db_healthy(tmp_path, tries=2, interval_seconds=0)


def test_wait_db_healthy_handles_none_status(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "ps_status", lambda repo_root, service: None)
    with pytest.raises(db.DbError):
        db.wait_db_healthy(tmp_path, tries=1, interval_seconds=0)


# --- backup ---

def _patch_backup_common(
    monkeypatch, dump_content=b"dump-bytes", toc_lines=("...  TABLE DATA  foo",), counts_stdout="employees:3\n"
):
    monkeypatch.setattr(compose, "up_db", lambda repo_root: _cp())
    monkeypatch.setattr(compose, "ps_status", lambda repo_root, service: "healthy")

    def fake_binary(repo_root, args, dest: Path):
        dest.write_bytes(dump_content)
        return _bcp(returncode=0)

    monkeypatch.setattr(compose, "exec_in_db_binary_stdout", fake_binary)
    monkeypatch.setattr(compose, "db_env", lambda repo_root, var: {"POSTGRES_USER": "u", "POSTGRES_DB": "d"}[var])
    monkeypatch.setattr(compose, "cp_to_db", lambda repo_root, local_path, dest: _cp())

    def fake_exec(repo_root, args):
        if args[:2] == ["pg_restore", "-l"]:
            return _cp(stdout="\n".join(toc_lines))
        if args and args[0] == "psql" and "-Atc" in args:
            return _cp(stdout=counts_stdout)
        return _cp()

    monkeypatch.setattr(compose, "exec_in_db", fake_exec)


def test_backup_success(tmp_path, monkeypatch):
    _patch_backup_common(monkeypatch)
    backups_dir = tmp_path / "backups"
    logs = []
    result = db.backup(tmp_path, backups_dir=backups_dir, log=logs.append)
    assert result.dump_path.exists()
    assert result.dump_path.read_bytes() == b"dump-bytes"
    assert result.table_count == 1
    assert result.counts_path.read_text(encoding="utf-8") == "employees:3\n"
    assert any("Backup completato" in m for m in logs)


def test_backup_empty_dump_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "up_db", lambda repo_root: _cp())
    monkeypatch.setattr(compose, "ps_status", lambda repo_root, service: "healthy")
    monkeypatch.setattr(compose, "db_env", lambda repo_root, var: {"POSTGRES_USER": "u", "POSTGRES_DB": "d"}[var])

    def fake_binary(repo_root, args, dest: Path):
        return _bcp(returncode=1, stderr=b"pg_dump failed")

    monkeypatch.setattr(compose, "exec_in_db_binary_stdout", fake_binary)
    with pytest.raises(db.DbError, match="pg_dump failed"):
        db.backup(tmp_path, backups_dir=tmp_path / "backups")


def test_backup_no_tables_raises(tmp_path, monkeypatch):
    _patch_backup_common(monkeypatch, toc_lines=("no tables here",))
    with pytest.raises(db.DbError, match="TABLE DATA"):
        db.backup(tmp_path, backups_dir=tmp_path / "backups")


# --- restore ---

def _patch_restore_common(monkeypatch, already_migrated="", restore_rc=0, restore_stderr=""):
    monkeypatch.setattr(compose, "up_db", lambda repo_root: _cp())
    monkeypatch.setattr(compose, "ps_status", lambda repo_root, service: "healthy")
    monkeypatch.setattr(compose, "db_env", lambda repo_root, var: {"POSTGRES_USER": "u", "POSTGRES_DB": "d"}[var])
    monkeypatch.setattr(compose, "cp_to_db", lambda repo_root, local_path, dest: _cp())

    state = {"migrated": already_migrated, "count_response": ""}

    def fake_exec(repo_root, args):
        joined = " ".join(args)
        if "to_regclass" in joined:
            return _cp(stdout=state["migrated"])
        if args[:1] == ["pg_restore"]:
            return _cp(returncode=restore_rc, stderr=restore_stderr)
        if args[:1] == ["rm"]:
            return _cp()
        if args[:1] == ["psql"] and "count(*)" in joined:
            return _cp(stdout=state["count_response"])
        return _cp()

    monkeypatch.setattr(compose, "exec_in_db", fake_exec)
    return state


def test_restore_noop_when_already_migrated(tmp_path, monkeypatch):
    _patch_restore_common(monkeypatch, already_migrated="alembic_version")
    result = db.restore(tmp_path, backups_dir=tmp_path / "backups")
    assert result.performed is False
    assert result.dump_path is None
    assert result.mismatches == []


def test_restore_no_dump_found_raises(tmp_path, monkeypatch):
    _patch_restore_common(monkeypatch, already_migrated="")
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    with pytest.raises(db.DbError, match="nessuno schema"):
        db.restore(tmp_path, backups_dir=backups_dir)


def test_restore_explicit_dump_path_not_file_raises(tmp_path, monkeypatch):
    _patch_restore_common(monkeypatch, already_migrated="")
    with pytest.raises(db.DbError, match="non trovato"):
        db.restore(tmp_path, dump_path=tmp_path / "nope.dump", backups_dir=tmp_path / "backups")


def test_restore_success_without_counts_file(tmp_path, monkeypatch):
    _patch_restore_common(monkeypatch, already_migrated="")
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    dump_path = backups_dir / "payroll_20260101T000000Z.dump"
    dump_path.write_bytes(b"dump")
    logs = []
    result = db.restore(tmp_path, backups_dir=backups_dir, log=logs.append)
    assert result.performed is True
    assert result.dump_path == dump_path
    assert result.mismatches == []
    assert any("salto la verifica" in m for m in logs)


def test_restore_pg_restore_failure_raises(tmp_path, monkeypatch):
    _patch_restore_common(monkeypatch, already_migrated="", restore_rc=1, restore_stderr="corrupt")
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    dump_path = backups_dir / "payroll_20260101T000000Z.dump"
    dump_path.write_bytes(b"dump")
    with pytest.raises(db.DbError, match="corrupt"):
        db.restore(tmp_path, backups_dir=backups_dir)


def test_restore_counts_mismatch_raises(tmp_path, monkeypatch):
    state = _patch_restore_common(monkeypatch, already_migrated="")
    state["count_response"] = "5"
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    dump_path = backups_dir / "payroll_20260101T000000Z.dump"
    dump_path.write_bytes(b"dump")
    counts_path = dump_path.with_suffix(dump_path.suffix + ".counts")
    counts_path.write_text("employees:3\n", encoding="utf-8")
    with pytest.raises(db.DbError, match="employees atteso=3 trovato=5"):
        db.restore(tmp_path, backups_dir=backups_dir)


def test_restore_counts_match_ok(tmp_path, monkeypatch):
    state = _patch_restore_common(monkeypatch, already_migrated="")
    state["count_response"] = "3"
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    dump_path = backups_dir / "payroll_20260101T000000Z.dump"
    dump_path.write_bytes(b"dump")
    counts_path = dump_path.with_suffix(dump_path.suffix + ".counts")
    counts_path.write_text("employees:3\n", encoding="utf-8")
    logs = []
    result = db.restore(tmp_path, backups_dir=backups_dir, log=logs.append)
    assert result.performed is True
    assert result.mismatches == []
    assert any("verificati: OK" in m for m in logs)


def test_restore_counts_file_ignores_malformed_lines(tmp_path, monkeypatch):
    """Righe senza ':' nel file .counts (es. vuote) vengono saltate invece di
    far esplodere lo split."""
    state = _patch_restore_common(monkeypatch, already_migrated="")
    state["count_response"] = "3"
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    dump_path = backups_dir / "payroll_20260101T000000Z.dump"
    dump_path.write_bytes(b"dump")
    counts_path = dump_path.with_suffix(dump_path.suffix + ".counts")
    counts_path.write_text("\nemployees:3\n", encoding="utf-8")
    result = db.restore(tmp_path, backups_dir=backups_dir)
    assert result.performed is True
    assert result.mismatches == []


def test_restore_uses_latest_dump_automatically(tmp_path, monkeypatch):
    _patch_restore_common(monkeypatch, already_migrated="")
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    older = backups_dir / "payroll_20260101T000000Z.dump"
    older.write_bytes(b"old")
    newer = backups_dir / "payroll_20260102T000000Z.dump"
    newer.write_bytes(b"new")
    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(newer, (now, now))
    result = db.restore(tmp_path, backups_dir=backups_dir)
    assert result.dump_path == newer


# --- migrate ---

def test_migrate_success(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "run_in_app", lambda repo_root, args: _cp(returncode=0))
    db.migrate(tmp_path)  # non deve sollevare


def test_migrate_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "run_in_app", lambda repo_root, args: _cp(returncode=1, stderr="boom"))
    with pytest.raises(db.DbError, match="boom"):
        db.migrate(tmp_path)


def test_migrate_passes_revision_through(tmp_path, monkeypatch):
    captured = {}

    def fake_run_in_app(repo_root, args):
        captured["args"] = args
        return _cp(returncode=0)

    monkeypatch.setattr(compose, "run_in_app", fake_run_in_app)
    db.migrate(tmp_path, revision="abc123")
    assert captured["args"] == ["alembic", "upgrade", "abc123"]


# --- shell ---

def test_shell_returns_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "db_env", lambda repo_root, var: {"POSTGRES_USER": "u", "POSTGRES_DB": "d"}[var])
    monkeypatch.setattr(compose, "exec_in_db_interactive", lambda repo_root, args: 7)
    assert db.shell(tmp_path) == 7
