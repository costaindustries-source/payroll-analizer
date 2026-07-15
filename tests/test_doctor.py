"""Test per le probe di 'payroll setup' in payroll_cli.doctor.

Mocka shutil.which / subprocess.run / shutil.disk_usage / os.getuid-getgid:
niente comandi reali, niente dipendenza dall'ambiente host in cui girano
i test.
"""

import payroll_cli.doctor as doctor_mod


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeDiskUsage:
    def __init__(self, free_bytes):
        self.free = free_bytes
        self.total = free_bytes * 2
        self.used = free_bytes


def test_tool_version_not_in_path(monkeypatch):
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _name: None)
    ok, detail = doctor_mod._tool_version(["ghost-tool", "--version"])
    assert ok is False
    assert "ghost-tool" in detail
    assert "non trovato" in detail


def test_tool_version_success_first_line_only(monkeypatch):
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        doctor_mod.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="Docker version 24.0\nextra\n")
    )
    ok, detail = doctor_mod._tool_version(["docker", "--version"])
    assert ok is True
    assert detail == "Docker version 24.0"


def test_tool_version_success_empty_output_reports_ok(monkeypatch):
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(doctor_mod.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout=""))
    ok, detail = doctor_mod._tool_version(["tool", "--version"])
    assert ok is True
    assert detail == "OK"


def test_tool_version_nonzero_exit_uses_stderr(monkeypatch):
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        doctor_mod.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1, stdout="", stderr="daemon not running")
    )
    ok, detail = doctor_mod._tool_version(["docker", "compose", "version"])
    assert ok is False
    assert detail == "daemon not running"


def test_tool_version_nonzero_exit_no_output_uses_default_message(monkeypatch):
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(doctor_mod.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1))
    ok, detail = doctor_mod._tool_version(["docker", "compose", "version"])
    assert ok is False
    assert "ha restituito un errore" in detail


def _mock_all_tools_present(monkeypatch, tool_returncode=0):
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(
        doctor_mod.subprocess,
        "run",
        lambda args, **k: _FakeCompleted(returncode=tool_returncode, stdout=f"{args[0]} ok"),
    )


def test_run_checks_all_ok_uid_matches(monkeypatch, tmp_path):
    _mock_all_tools_present(monkeypatch)
    monkeypatch.setattr(doctor_mod.shutil, "disk_usage", lambda _path: _FakeDiskUsage(free_bytes=10 * 1024**3))
    if hasattr(doctor_mod.os, "getuid"):
        monkeypatch.setattr(doctor_mod.os, "getuid", lambda: 1000)
        monkeypatch.setattr(doctor_mod.os, "getgid", lambda: 1000)

    results = doctor_mod.run_checks(tmp_path)
    names = {r.name: r for r in results}
    assert set(names) == {"docker", "docker compose", "git", "uv", "spazio disco", "UID/GID host"}
    assert all(r.ok for r in results)
    assert names["uv"].blocking is False
    assert names["docker"].blocking is True


def test_run_checks_low_disk_space_not_ok(monkeypatch, tmp_path):
    _mock_all_tools_present(monkeypatch)
    monkeypatch.setattr(doctor_mod.shutil, "disk_usage", lambda _path: _FakeDiskUsage(free_bytes=int(0.5 * 1024**3)))
    if hasattr(doctor_mod.os, "getuid"):
        monkeypatch.setattr(doctor_mod.os, "getuid", lambda: 1000)
        monkeypatch.setattr(doctor_mod.os, "getgid", lambda: 1000)

    results = doctor_mod.run_checks(tmp_path)
    disk_check = next(r for r in results if r.name == "spazio disco")
    assert disk_check.ok is False
    assert "0.5" in disk_check.detail


def test_run_checks_uid_mismatch_not_blocking(monkeypatch, tmp_path):
    _mock_all_tools_present(monkeypatch)
    monkeypatch.setattr(doctor_mod.shutil, "disk_usage", lambda _path: _FakeDiskUsage(free_bytes=10 * 1024**3))
    if not hasattr(doctor_mod.os, "getuid"):
        return  # su Windows questo check e' saltato: nulla da verificare qui
    monkeypatch.setattr(doctor_mod.os, "getuid", lambda: 1001)
    monkeypatch.setattr(doctor_mod.os, "getgid", lambda: 1001)

    results = doctor_mod.run_checks(tmp_path)
    uid_check = next(r for r in results if r.name == "UID/GID host")
    assert uid_check.ok is False
    assert uid_check.blocking is False
    assert "1001:1001" in uid_check.detail
    assert "1000:1000" in uid_check.detail


def test_run_checks_windows_no_getuid_skips_check(monkeypatch, tmp_path):
    _mock_all_tools_present(monkeypatch)
    monkeypatch.setattr(doctor_mod.shutil, "disk_usage", lambda _path: _FakeDiskUsage(free_bytes=10 * 1024**3))
    monkeypatch.delattr(doctor_mod.os, "getuid", raising=False)
    monkeypatch.delattr(doctor_mod.os, "getgid", raising=False)

    results = doctor_mod.run_checks(tmp_path)
    uid_check = next(r for r in results if r.name == "UID/GID host")
    assert uid_check.ok is True
    assert uid_check.blocking is False
    assert "non applicabile su Windows" in uid_check.detail


def test_check_result_dataclass_defaults():
    result = doctor_mod.CheckResult(name="x", ok=True, detail="d")
    assert result.blocking is True
