"""Test per payroll_cli.setup_wizard: scrittura config per-macchina, override
compose, password Postgres per-macchina, bootstrap (build/avvio/migration/
smoke test). compose/db sono sempre mockati: mai una chiamata docker reale."""

from types import SimpleNamespace

import tomllib

from payroll_cli import compose, db as db_module, setup_wizard
from payroll_cli.context import MachineConfig


def _cp(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_default_machine_name(monkeypatch):
    monkeypatch.setattr(setup_wizard.socket, "gethostname", lambda: "mio-host")
    assert setup_wizard.default_machine_name() == "mio-host"


def test_write_config_roundtrip(tmp_path):
    config = MachineConfig(
        name="nodo1", role="node", db_host_port=5433, auto_backup=False,
        logs_retention_days=30, backups_keep=3,
    )
    path = setup_wizard.write_config(tmp_path, config)
    assert path == tmp_path / "payroll.local.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["machine"] == {"name": "nodo1", "role": "node"}
    assert data["db"] == {"host_port": 5433}
    assert data["update"] == {"auto_backup": False}
    assert data["cleanup"] == {"logs_retention_days": 30, "backups_keep": 3}


def test_maybe_write_override_default_port_noop(tmp_path):
    assert setup_wizard.maybe_write_override(tmp_path, 5432) is None
    assert not (tmp_path / "docker-compose.override.yml").exists()


def test_maybe_write_override_creates_file(tmp_path):
    logs = []
    path = setup_wizard.maybe_write_override(tmp_path, 5544, log=logs.append)
    assert path == tmp_path / "docker-compose.override.yml"
    content = path.read_text(encoding="utf-8")
    assert "!override" in content
    assert '"127.0.0.1:5544:5432"' in content
    assert any("Generato" in m for m in logs)


def test_maybe_write_override_does_not_overwrite_existing(tmp_path):
    override_path = tmp_path / "docker-compose.override.yml"
    override_path.write_text("custom", encoding="utf-8")
    logs = []
    result = setup_wizard.maybe_write_override(tmp_path, 5544, log=logs.append)
    assert result == override_path
    assert override_path.read_text(encoding="utf-8") == "custom"
    assert any("non sovrascritto" in m for m in logs)


def test_ensure_env_password_creates_file(tmp_path):
    logs = []
    path = setup_wizard.ensure_env_password(tmp_path, log=logs.append)
    assert path == tmp_path / ".env"
    content = path.read_text(encoding="utf-8")
    assert content.startswith("POSTGRES_PASSWORD=")
    assert content.endswith("\n")
    assert any("Generata password" in m for m in logs)


def test_ensure_env_password_appends_to_existing_without_trailing_newline(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar", encoding="utf-8")
    setup_wizard.ensure_env_password(tmp_path)
    content = env_path.read_text(encoding="utf-8")
    assert content.startswith("FOO=bar\nPOSTGRES_PASSWORD=")


def test_ensure_env_password_appends_when_existing_already_ends_with_newline(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n", encoding="utf-8")
    setup_wizard.ensure_env_password(tmp_path)
    content = env_path.read_text(encoding="utf-8")
    # nessuna riga vuota aggiunta in mezzo: niente doppio '\n'
    assert "\n\n" not in content
    assert content.startswith("FOO=bar\nPOSTGRES_PASSWORD=")


def test_ensure_env_password_noop_if_already_present(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("POSTGRES_PASSWORD=already-set\n", encoding="utf-8")
    result = setup_wizard.ensure_env_password(tmp_path)
    assert result is None
    assert env_path.read_text(encoding="utf-8") == "POSTGRES_PASSWORD=already-set\n"


def test_bootstrap_build_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "build_app", lambda repo_root: _cp(returncode=1, stderr="boom"))
    try:
        setup_wizard.bootstrap(tmp_path)
        assert False, "doveva sollevare BootstrapError"
    except setup_wizard.BootstrapError as exc:
        assert "boom" in str(exc)


def test_bootstrap_success_without_samples(tmp_path, monkeypatch):
    logs = []
    monkeypatch.setattr(compose, "build_app", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(compose, "up_db", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(db_module, "wait_db_healthy", lambda repo_root: None)
    monkeypatch.setattr(db_module, "migrate", lambda repo_root: None)
    setup_wizard.bootstrap(tmp_path, log=logs.append)
    assert any("saltato" in m for m in logs)


def test_bootstrap_runs_smoke_test_when_samples_present(tmp_path, monkeypatch):
    samples_dir = tmp_path / "docs" / "payroll-test"
    samples_dir.mkdir(parents=True)
    (samples_dir / "sample.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(compose, "build_app", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(compose, "up_db", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(db_module, "wait_db_healthy", lambda repo_root: None)
    monkeypatch.setattr(db_module, "migrate", lambda repo_root: None)
    monkeypatch.setattr(setup_wizard.subprocess, "run", lambda *a, **k: _cp(returncode=0))

    setup_wizard.bootstrap(tmp_path)  # non deve sollevare


def test_bootstrap_smoke_test_failure_raises(tmp_path, monkeypatch):
    samples_dir = tmp_path / "docs" / "payroll-test"
    samples_dir.mkdir(parents=True)
    (samples_dir / "sample.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(compose, "build_app", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(compose, "up_db", lambda repo_root: _cp(returncode=0))
    monkeypatch.setattr(db_module, "wait_db_healthy", lambda repo_root: None)
    monkeypatch.setattr(db_module, "migrate", lambda repo_root: None)
    monkeypatch.setattr(setup_wizard.subprocess, "run", lambda *a, **k: _cp(returncode=1))

    try:
        setup_wizard.bootstrap(tmp_path)
        assert False, "doveva sollevare BootstrapError"
    except setup_wizard.BootstrapError:
        pass
