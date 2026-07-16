"""Test per i wrapper docker compose in payroll_cli.compose.

Mocka sempre subprocess.run: non deve mai lanciare 'docker compose' reale
(lento, side-effect su container reali dell'utente). Verifica gli argomenti
costruiti e il parsing dell'output.
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import payroll_cli.compose as compose_mod


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _capture_run(monkeypatch, result=None):
    """Sostituisce subprocess.run con uno che registra la chiamata e ritorna `result`."""
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return result or _FakeCompleted()

    monkeypatch.setattr(compose_mod.subprocess, "run", fake_run)
    return calls


def test_ps_status_running(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch, _FakeCompleted(stdout="Up 2 minutes\n"))
    status = compose_mod.ps_status(tmp_path, "db")
    assert status == "Up 2 minutes"
    (args, kwargs) = calls[0]
    assert args[0] == ["docker", "compose", "ps", "db", "--format", "{{.Status}}"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_ps_status_not_running_returns_none(monkeypatch, tmp_path):
    _capture_run(monkeypatch, _FakeCompleted(stdout="  \n"))
    assert compose_mod.ps_status(tmp_path, "db") is None


def test_exec_in_db_builds_expected_args(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    compose_mod.exec_in_db(tmp_path, ["psql", "-c", "select 1"])
    (args, kwargs) = calls[0]
    assert args[0] == ["docker", "compose", "exec", "-T", "db", "psql", "-c", "select 1"]
    assert kwargs["cwd"] == tmp_path


def test_run_in_app_builds_expected_args(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    compose_mod.run_in_app(tmp_path, ["python", "manage.py", "migrate"])
    (args, _kwargs) = calls[0]
    assert args[0] == ["docker", "compose", "run", "--rm", "app", "python", "manage.py", "migrate"]


def test_db_env_success(monkeypatch, tmp_path):
    _capture_run(monkeypatch, _FakeCompleted(returncode=0, stdout="secret-value\n"))
    assert compose_mod.db_env(tmp_path, "POSTGRES_PASSWORD") == "secret-value"


def test_db_env_failure_returns_none(monkeypatch, tmp_path):
    _capture_run(monkeypatch, _FakeCompleted(returncode=1, stdout=""))
    assert compose_mod.db_env(tmp_path, "MISSING_VAR") is None


def test_db_is_running_true(monkeypatch, tmp_path):
    _capture_run(monkeypatch, _FakeCompleted(stdout="Up 5 minutes (healthy)\n"))
    assert compose_mod.db_is_running(tmp_path) is True


def test_db_is_running_false_when_not_running(monkeypatch, tmp_path):
    _capture_run(monkeypatch, _FakeCompleted(stdout=""))
    assert compose_mod.db_is_running(tmp_path) is False


def test_db_is_running_false_when_exited(monkeypatch, tmp_path):
    _capture_run(monkeypatch, _FakeCompleted(stdout="Exited (0) 2 minutes ago\n"))
    assert compose_mod.db_is_running(tmp_path) is False


def test_up_db_builds_expected_args(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    compose_mod.up_db(tmp_path)
    (args, _kwargs) = calls[0]
    assert args[0] == ["docker", "compose", "up", "-d", "db"]


def test_build_app_builds_expected_args(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    compose_mod.build_app(tmp_path)
    (args, _kwargs) = calls[0]
    assert args[0] == ["docker", "compose", "build", "app"]


def test_cp_to_db_builds_expected_args(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    compose_mod.cp_to_db(tmp_path, tmp_path / "dump.sql", "/tmp/dump.sql")
    (args, _kwargs) = calls[0]
    assert args[0] == ["docker", "compose", "cp", str(tmp_path / "dump.sql"), "db:/tmp/dump.sql"]


def _dispatch_by_subcommand(responses):
    """fake_run che sceglie la risposta in base al secondo argomento del comando
    docker (['docker', 'compose', 'config', ...] vs ['docker', 'inspect', ...]),
    per testare app_image_created_at che incatena due chiamate subprocess."""

    def fake_run(args, **kwargs):
        key = args[1]
        return responses[key]

    return fake_run


def test_app_image_created_at_parses_inspect_output(monkeypatch, tmp_path):
    fake_run = _dispatch_by_subcommand(
        {
            "compose": _FakeCompleted(returncode=0, stdout="payroll-analizer-app\n"),
            "inspect": _FakeCompleted(returncode=0, stdout="2026-07-14T15:20:19.123456+00:00\n"),
        }
    )
    monkeypatch.setattr(compose_mod.subprocess, "run", fake_run)
    result = compose_mod.app_image_created_at(tmp_path)
    assert result == datetime(2026, 7, 14, 15, 20, 19, 123456, tzinfo=timezone.utc)


def test_app_image_created_at_none_when_image_not_built(monkeypatch, tmp_path):
    fake_run = _dispatch_by_subcommand(
        {
            "compose": _FakeCompleted(returncode=0, stdout=""),
        }
    )
    monkeypatch.setattr(compose_mod.subprocess, "run", fake_run)
    assert compose_mod.app_image_created_at(tmp_path) is None


def test_app_image_created_at_none_when_config_fails(monkeypatch, tmp_path):
    fake_run = _dispatch_by_subcommand(
        {
            "compose": _FakeCompleted(returncode=1, stdout=""),
        }
    )
    monkeypatch.setattr(compose_mod.subprocess, "run", fake_run)
    assert compose_mod.app_image_created_at(tmp_path) is None


def test_app_image_created_at_none_when_inspect_fails(monkeypatch, tmp_path):
    fake_run = _dispatch_by_subcommand(
        {
            "compose": _FakeCompleted(returncode=0, stdout="payroll-analizer-app\n"),
            "inspect": _FakeCompleted(returncode=1, stdout=""),
        }
    )
    monkeypatch.setattr(compose_mod.subprocess, "run", fake_run)
    assert compose_mod.app_image_created_at(tmp_path) is None


def test_app_image_created_at_none_when_timestamp_unparseable(monkeypatch, tmp_path):
    fake_run = _dispatch_by_subcommand(
        {
            "compose": _FakeCompleted(returncode=0, stdout="payroll-analizer-app\n"),
            "inspect": _FakeCompleted(returncode=0, stdout="not-a-timestamp\n"),
        }
    )
    monkeypatch.setattr(compose_mod.subprocess, "run", fake_run)
    assert compose_mod.app_image_created_at(tmp_path) is None


def test_exec_in_db_binary_stdout_writes_file_and_uses_binary_mode(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        kwargs["stdout"].write(b"binary-data")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(compose_mod.subprocess, "run", fake_run)
    dest = tmp_path / "dump.bin"
    result = compose_mod.exec_in_db_binary_stdout(tmp_path, ["pg_dump", "-Fc"], dest)

    assert result.returncode == 0
    assert captured["args"] == ["docker", "compose", "exec", "-T", "db", "pg_dump", "-Fc"]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert "text" not in captured["kwargs"]  # niente text=True: corromperebbe i binari
    assert dest.read_bytes() == b"binary-data"


def test_exec_in_db_interactive_returns_returncode(monkeypatch, tmp_path):
    def fake_run(args, **kwargs):
        assert args == ["docker", "compose", "exec", "db", "psql"]
        assert kwargs["cwd"] == tmp_path
        assert "capture_output" not in kwargs  # eredita stdio reale del terminale
        return _FakeCompleted(returncode=3)

    monkeypatch.setattr(compose_mod.subprocess, "run", fake_run)
    rc = compose_mod.exec_in_db_interactive(tmp_path, ["psql"])
    assert rc == 3
