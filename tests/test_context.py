"""Test per la discovery del repo e la lettura di payroll.local.toml."""

import pytest

from payroll_cli.context import (
    Context,
    InvalidMachineConfigError,
    MachineConfig,
    RepoNotFoundError,
    find_repo_root,
    load_machine_config,
)


def _make_fake_repo(tmp_path):
    repo = tmp_path / "payroll-analizer"
    (repo / "packages" / "payroll-cli").mkdir(parents=True)
    (repo / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (repo / "packages" / "payroll-cli" / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return repo


def test_find_repo_root_env_override(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    monkeypatch.setenv("PAYROLL_REPO_ROOT", str(repo))
    assert find_repo_root() == repo.resolve()


def test_find_repo_root_env_override_invalid_raises(tmp_path, monkeypatch):
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    monkeypatch.setenv("PAYROLL_REPO_ROOT", str(empty))
    with pytest.raises(RepoNotFoundError, match="docker-compose.yml"):
        find_repo_root()


def test_find_repo_root_walks_up_from_subdirectory(tmp_path, monkeypatch):
    monkeypatch.delenv("PAYROLL_REPO_ROOT", raising=False)
    repo = _make_fake_repo(tmp_path)
    nested = repo / "some" / "nested" / "dir"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == repo.resolve()


def test_find_repo_root_not_found_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("PAYROLL_REPO_ROOT", raising=False)
    empty = tmp_path / "unrelated"
    empty.mkdir()
    with pytest.raises(RepoNotFoundError, match="non trovato"):
        find_repo_root(empty)


def test_find_repo_root_requires_both_markers(tmp_path, monkeypatch):
    """Un docker-compose.yml da solo (es. di un altro progetto) non basta."""
    monkeypatch.delenv("PAYROLL_REPO_ROOT", raising=False)
    other = tmp_path / "other-project"
    other.mkdir()
    (other / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    with pytest.raises(RepoNotFoundError):
        find_repo_root(other)


def test_load_machine_config_missing_file_returns_none(tmp_path):
    assert load_machine_config(tmp_path) is None


def test_load_machine_config_defaults(tmp_path):
    (tmp_path / "payroll.local.toml").write_text(
        '[machine]\nname = "laptop-1"\nrole = "node"\n', encoding="utf-8"
    )
    config = load_machine_config(tmp_path)
    assert config.name == "laptop-1"
    assert config.role == "node"
    assert config.db_host_port == 5432
    assert config.auto_backup is True
    assert config.logs_retention_days == 90
    assert config.backups_keep == 5
    assert config.is_source is False


def test_load_machine_config_source_role_and_overrides(tmp_path):
    (tmp_path / "payroll.local.toml").write_text(
        """
[machine]
name = "dev-box"
role = "source"

[db]
host_port = 5433

[update]
auto_backup = false

[cleanup]
logs_retention_days = 30
backups_keep = 10
""",
        encoding="utf-8",
    )
    config = load_machine_config(tmp_path)
    assert config.is_source is True
    assert config.db_host_port == 5433
    assert config.auto_backup is False
    assert config.logs_retention_days == 30
    assert config.backups_keep == 10


def test_load_machine_config_missing_name_defaults(tmp_path):
    (tmp_path / "payroll.local.toml").write_text('[machine]\nrole = "node"\n', encoding="utf-8")
    config = load_machine_config(tmp_path)
    assert config.name == "senza-nome"


def test_load_machine_config_invalid_role_raises(tmp_path):
    (tmp_path / "payroll.local.toml").write_text('[machine]\nrole = "bogus"\n', encoding="utf-8")
    with pytest.raises(InvalidMachineConfigError, match="role"):
        load_machine_config(tmp_path)


def test_load_machine_config_invalid_port_out_of_range_raises(tmp_path):
    (tmp_path / "payroll.local.toml").write_text(
        '[machine]\nrole = "node"\n\n[db]\nhost_port = 70000\n', encoding="utf-8"
    )
    with pytest.raises(InvalidMachineConfigError, match="host_port"):
        load_machine_config(tmp_path)


def test_load_machine_config_invalid_port_zero_raises(tmp_path):
    (tmp_path / "payroll.local.toml").write_text(
        '[machine]\nrole = "node"\n\n[db]\nhost_port = 0\n', encoding="utf-8"
    )
    with pytest.raises(InvalidMachineConfigError, match="host_port"):
        load_machine_config(tmp_path)


def test_load_machine_config_invalid_port_non_int_raises(tmp_path):
    (tmp_path / "payroll.local.toml").write_text(
        '[machine]\nrole = "node"\n\n[db]\nhost_port = "5432"\n', encoding="utf-8"
    )
    with pytest.raises(InvalidMachineConfigError, match="host_port"):
        load_machine_config(tmp_path)


def test_load_machine_config_invalid_port_bool_raises(tmp_path):
    """bool e' sottoclasse di int in Python: il controllo esplicito deve escluderlo."""
    (tmp_path / "payroll.local.toml").write_text(
        '[machine]\nrole = "node"\n\n[db]\nhost_port = true\n', encoding="utf-8"
    )
    with pytest.raises(InvalidMachineConfigError, match="host_port"):
        load_machine_config(tmp_path)


def test_machine_config_is_source_property():
    assert MachineConfig(name="x", role="source").is_source is True
    assert MachineConfig(name="x", role="node").is_source is False


def test_context_local_config_path(tmp_path):
    ctx = Context(repo_root=tmp_path, machine=None)
    assert ctx.local_config_path == tmp_path / "payroll.local.toml"
