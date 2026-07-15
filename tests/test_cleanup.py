"""Test per payroll_cli.cleanup: scan (report dry-run) e apply (rimozione).
Le chiamate 'docker images'/'docker inspect' (immagini dangling) sono sempre
mockate: nessuna chiamata docker reale."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from payroll_cli import cleanup
from payroll_cli.context import MachineConfig


def _cp(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode)


def _no_docker(monkeypatch):
    """docker images/inspect mockati: nessuna chiamata docker reale nello scan."""
    monkeypatch.setattr(cleanup.subprocess, "run", lambda *a, **k: _cp(stdout=""))


def test_size_missing_file_returns_zero(tmp_path):
    assert cleanup._size(tmp_path / "non-esiste") == 0


def test_scan_empty_repo_no_machine(tmp_path, monkeypatch):
    _no_docker(monkeypatch)
    report = cleanup.scan(tmp_path, None)
    assert report.work_residuals == []
    assert report.old_logs == []
    assert report.old_backups == []
    assert report.filesystem_items == []


def test_scan_work_residuals_skips_gitkeep(tmp_path, monkeypatch):
    _no_docker(monkeypatch)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / ".gitkeep").write_text("")
    (work_dir / "leftover.pdf").write_bytes(b"1234")
    report = cleanup.scan(tmp_path, None)
    assert [i.path.name for i in report.work_residuals] == ["leftover.pdf"]
    assert report.work_residuals[0].size_bytes == 4


def test_scan_old_logs_uses_retention_from_machine(tmp_path, monkeypatch):
    _no_docker(monkeypatch)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / ".gitkeep").write_text("")
    old_log = logs_dir / "old.log"
    old_log.write_text("x")
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(old_log, (old_time, old_time))
    (logs_dir / "recent.log").write_text("y")

    machine = MachineConfig(name="n", role="node", logs_retention_days=5)
    report = cleanup.scan(tmp_path, machine)
    assert [i.path.name for i in report.old_logs] == ["old.log"]
    assert "5 giorni" in report.old_logs[0].reason


def test_scan_old_logs_uses_default_retention_without_machine(tmp_path, monkeypatch):
    _no_docker(monkeypatch)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    old_log = logs_dir / "old.log"
    old_log.write_text("x")
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(old_log, (old_time, old_time))
    report = cleanup.scan(tmp_path, None)
    # default retention e' 90 giorni: un log di 10 giorni non e' ancora "vecchio"
    assert report.old_logs == []


def test_scan_old_backups_keeps_most_recent(tmp_path, monkeypatch):
    _no_docker(monkeypatch)
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    now = datetime.now(timezone.utc).timestamp()
    for i, name in enumerate(["payroll_1.dump", "payroll_2.dump", "payroll_3.dump"]):
        p = backups_dir / name
        p.write_bytes(b"dump")
        os.utime(p, (now - i, now - i))  # payroll_1 e' il piu' recente (mtime maggiore)
    (backups_dir / "payroll_2.dump.counts").write_text("counts")

    machine = MachineConfig(name="n", role="node", backups_keep=1)
    report = cleanup.scan(tmp_path, machine)
    kept_names = {i.path.name for i in report.old_backups}
    assert kept_names == {"payroll_2.dump", "payroll_3.dump"}
    item2 = next(i for i in report.old_backups if i.path.name == "payroll_2.dump")
    assert item2.extra_paths == [backups_dir / "payroll_2.dump.counts"]
    item3 = next(i for i in report.old_backups if i.path.name == "payroll_3.dump")
    assert item3.extra_paths == []


def test_scan_dangling_images_reports_count_and_size(tmp_path, monkeypatch):
    def fake_run(args, **kwargs):
        if args[:2] == ["docker", "images"]:
            return _cp(stdout="id1\nid2\n")
        if args[:2] == ["docker", "inspect"]:
            return _cp(stdout="100\n200\n")
        return _cp()

    monkeypatch.setattr(cleanup.subprocess, "run", fake_run)
    report = cleanup.scan(tmp_path, None)
    assert report.dangling_images_count == 2
    assert report.dangling_images_size_bytes == 300


def test_scan_dangling_images_none_skips_inspect_call(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _cp(stdout="")

    monkeypatch.setattr(cleanup.subprocess, "run", fake_run)
    report = cleanup.scan(tmp_path, None)
    assert report.dangling_images_count == 0
    assert report.dangling_images_size_bytes == 0
    assert len(calls) == 1  # solo 'docker images', mai 'docker inspect' se non ci sono id


def test_apply_removes_files_dirs_and_extra_paths(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    d = tmp_path / "adir"
    d.mkdir()
    (d / "inner.txt").write_text("y")
    extra = tmp_path / "a.txt.counts"
    extra.write_text("z")

    report = cleanup.CleanupReport(
        work_residuals=[cleanup.CleanupItem(f, "test", 1, extra_paths=[extra])],
        old_backups=[cleanup.CleanupItem(d, "test", 1)],
    )
    logs = []
    cleanup.apply(report, log=logs.append)
    assert not f.exists()
    assert not d.exists()
    assert not extra.exists()
    assert len(logs) == 2
