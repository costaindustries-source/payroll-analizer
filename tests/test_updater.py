"""Test per payroll_cli.updater ('payroll update apply' / 'payroll rollback'):
risoluzione tag target, blocco su working tree sporco, resume post-checkout.
Le operazioni git usano repo reali in tmp_path (nessun remote configurato,
nessuna rete coinvolta); compose/db sono sempre mockati."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from payroll_cli import compose, db as db_module, git_ops, updater


def _cp(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _git(repo_root, *args):
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _init_repo(repo_root: Path) -> None:
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")


def _commit_compose(repo_root: Path, volume_name: str, message: str) -> None:
    # commento col messaggio: garantisce un contenuto diverso a ogni commit
    # anche quando il volume resta lo stesso (altrimenti 'git commit' fallisce
    # per assenza di modifiche).
    content = (
        f"# {message}\n"
        "services:\n"
        "  db:\n"
        "    volumes:\n"
        f"      - {volume_name}:/var/lib/postgresql/data\n"
    )
    (repo_root / "docker-compose.yml").write_text(content, encoding="utf-8")
    _git(repo_root, "add", "docker-compose.yml")
    _git(repo_root, "commit", "-q", "-m", message)


# --- resolve_target ---

def test_resolve_target_explicit_tag_found(tmp_path, monkeypatch):
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.0.0", "v1.1.0"])
    assert updater.resolve_target(tmp_path, "v1.0.0") == "v1.0.0"


def test_resolve_target_explicit_tag_not_found_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.0.0"])
    with pytest.raises(updater.UpdateError):
        updater.resolve_target(tmp_path, "v9.9.9")


def test_resolve_target_defaults_to_latest_semver(tmp_path, monkeypatch):
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.0.0", "v1.2.0", "v1.1.0"])
    assert updater.resolve_target(tmp_path, None) == "v1.2.0"


def test_resolve_target_no_tags_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: [])
    with pytest.raises(updater.UpdateError):
        updater.resolve_target(tmp_path, None)


# --- _pg_volume_name / pg_volume_changed (repo git reale) ---

def test_pg_volume_name_reads_from_ref(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata_v1", "v1")
    _git(tmp_path, "tag", "v1.0.0")
    assert updater._pg_volume_name(tmp_path, "v1.0.0") == "pgdata_v1"


def test_pg_volume_name_unreadable_ref_returns_none(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata_v1", "v1")
    assert updater._pg_volume_name(tmp_path, "does-not-exist") is None


def test_pg_volume_changed_true_when_name_differs(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata_v1", "v1")
    _git(tmp_path, "tag", "v1.0.0")
    _commit_compose(tmp_path, "pgdata_v2", "v2")
    _git(tmp_path, "tag", "v2.0.0")
    assert updater.pg_volume_changed(tmp_path, "v1.0.0", "v2.0.0") is True


def test_pg_volume_changed_false_when_name_same(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata_v1", "v1")
    _git(tmp_path, "tag", "v1.0.0")
    _commit_compose(tmp_path, "pgdata_v1", "v1 bis")
    _git(tmp_path, "tag", "v1.0.1")
    assert updater.pg_volume_changed(tmp_path, "v1.0.0", "v1.0.1") is False


def test_pg_volume_changed_assumes_true_if_ref_unreadable(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata_v1", "v1")
    _git(tmp_path, "tag", "v1.0.0")
    assert updater.pg_volume_changed(tmp_path, "v1.0.0", "nope") is True


# --- ensure_clean_worktree / checkout (repo git reale) ---

def test_ensure_clean_worktree_ok_when_clean(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata", "init")
    updater.ensure_clean_worktree(tmp_path)  # non deve sollevare


def test_ensure_clean_worktree_raises_when_dirty(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata", "init")
    (tmp_path / "docker-compose.yml").write_text("dirty", encoding="utf-8")
    with pytest.raises(updater.UpdateError):
        updater.ensure_clean_worktree(tmp_path)


def test_checkout_success(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata", "init")
    _git(tmp_path, "tag", "v1.0.0")
    updater.checkout(tmp_path, "v1.0.0")
    assert git_ops.exact_tag_on_head(tmp_path) == "v1.0.0"


def test_checkout_failure_raises(tmp_path):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata", "init")
    with pytest.raises(updater.UpdateError):
        updater.checkout(tmp_path, "does-not-exist")


# --- _run_smoke_test ---

def test_run_smoke_test_skips_without_samples(tmp_path):
    logs = []
    updater._run_smoke_test(tmp_path, logs.append)
    assert any("saltato" in m for m in logs)


def test_run_smoke_test_runs_and_raises_on_failure(tmp_path, monkeypatch):
    samples_dir = tmp_path / "docs" / "payroll-test"
    samples_dir.mkdir(parents=True)
    (samples_dir / "s.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: _cp(returncode=1))
    with pytest.raises(updater.UpdateError):
        updater._run_smoke_test(tmp_path, print)


def test_run_smoke_test_runs_success(tmp_path, monkeypatch):
    samples_dir = tmp_path / "docs" / "payroll-test"
    samples_dir.mkdir(parents=True)
    (samples_dir / "s.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: _cp(returncode=0))
    updater._run_smoke_test(tmp_path, print)  # non deve sollevare


# --- resume ---

def _patch_resume_ok(monkeypatch, restore_performed=True, dump_path=None):
    monkeypatch.setattr(compose, "build_app", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(compose, "up_db", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(db_module, "wait_db_healthy", lambda repo_root: None)
    monkeypatch.setattr(
        db_module, "restore",
        lambda repo_root, log=print: db_module.RestoreResult(
            performed=restore_performed, dump_path=dump_path, mismatches=[]
        ),
    )
    monkeypatch.setattr(db_module, "migrate", lambda repo_root: None)


def test_resume_build_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "build_app", lambda repo_root: _cp(returncode=1, stderr="boom"))
    with pytest.raises(updater.UpdateError):
        updater.resume(tmp_path)


def test_resume_restore_error_wrapped(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "build_app", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(compose, "up_db", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(db_module, "wait_db_healthy", lambda repo_root: None)

    def raise_restore(repo_root, log=print):
        raise db_module.DbError("restore fallito")

    monkeypatch.setattr(db_module, "restore", raise_restore)
    with pytest.raises(updater.UpdateError, match="restore fallito"):
        updater.resume(tmp_path)


def test_resume_migrate_error_wrapped(tmp_path, monkeypatch):
    _patch_resume_ok(monkeypatch, restore_performed=False)

    def raise_migrate(repo_root):
        raise db_module.DbError("migrate fallito")

    monkeypatch.setattr(db_module, "migrate", raise_migrate)
    with pytest.raises(updater.UpdateError, match="migrate fallito"):
        updater.resume(tmp_path)


def test_resume_success_no_samples(tmp_path, monkeypatch):
    logs = []
    _patch_resume_ok(monkeypatch, restore_performed=True, dump_path=tmp_path / "backups" / "payroll_x.dump")
    updater.resume(tmp_path, log=logs.append)
    assert any("Dati ripristinati" in m for m in logs)
    assert any("saltato" in m for m in logs)


# --- reexec_resume ---

def test_reexec_resume_builds_args_without_previous_tag(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, cwd=None):
        captured["args"] = args
        captured["cwd"] = cwd
        return _cp(returncode=0)

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    rc = updater.reexec_resume(tmp_path, None)
    assert rc == 0
    assert captured["args"] == ["uv", "run", "payroll", "update", "apply", "--resume"]
    assert captured["cwd"] == tmp_path


def test_reexec_resume_builds_args_with_previous_tag(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, cwd=None):
        captured["args"] = args
        return _cp(returncode=3)

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    rc = updater.reexec_resume(tmp_path, "v1.0.0")
    assert rc == 3
    assert captured["args"] == [
        "uv", "run", "payroll", "update", "apply", "--resume", "--previous-tag", "v1.0.0",
    ]


# --- log_update ---

def test_log_update_appends_line(tmp_path):
    updater.log_update(tmp_path, "v1.0.0", "v1.1.0", "ok")
    updater.log_update(tmp_path, "v1.1.0", "v1.2.0", "fallito")
    content = (tmp_path / "logs" / "updates.log").read_text(encoding="utf-8")
    lines = content.splitlines()
    assert len(lines) == 2
    assert "v1.0.0 -> v1.1.0" in lines[0]
    assert lines[0].endswith("ok")


def test_log_update_unknown_from_tag(tmp_path):
    updater.log_update(tmp_path, None, "v1.0.0", "ok")
    content = (tmp_path / "logs" / "updates.log").read_text(encoding="utf-8")
    assert "? -> v1.0.0" in content


# --- do_rollback ---

def test_do_rollback_dirty_raises_before_checkout(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata", "init")
    _git(tmp_path, "tag", "v1.0.0")
    (tmp_path / "docker-compose.yml").write_text("dirty", encoding="utf-8")
    called = []
    monkeypatch.setattr(compose, "build_app", lambda repo_root: called.append(True) or _cp(returncode=0))
    with pytest.raises(updater.UpdateError):
        updater.do_rollback(tmp_path, "v1.0.0")
    assert not called


def test_do_rollback_checks_out_and_builds(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata_v1", "v1")
    _git(tmp_path, "tag", "v1.0.0")
    _commit_compose(tmp_path, "pgdata_v2", "v2")
    _git(tmp_path, "tag", "v2.0.0")

    calls = []
    monkeypatch.setattr(compose, "build_app", lambda repo_root: calls.append(True) or _cp(returncode=0))
    updater.do_rollback(tmp_path, "v1.0.0")
    assert calls == [True]
    assert "pgdata_v1" in (tmp_path / "docker-compose.yml").read_text(encoding="utf-8")
    assert git_ops.exact_tag_on_head(tmp_path) == "v1.0.0"


def test_do_rollback_build_failure_raises(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    _commit_compose(tmp_path, "pgdata", "init")
    _git(tmp_path, "tag", "v1.0.0")
    monkeypatch.setattr(compose, "build_app", lambda repo_root: _cp(returncode=1, stderr="boom"))
    with pytest.raises(updater.UpdateError):
        updater.do_rollback(tmp_path, "v1.0.0")
