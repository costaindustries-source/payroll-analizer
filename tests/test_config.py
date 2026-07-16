from pathlib import Path

from payroll_ingest.config import Settings, get_settings


def test_settings_defaults():
    settings = Settings()
    assert settings.base_dir == Path(".")
    assert settings.input_dir_name == "input"
    assert settings.processed_dir_name == "processed"
    assert settings.error_dir_name == "error"
    assert settings.logs_dir_name == "logs"
    assert settings.export_dir_name == "export"
    assert settings.work_dir_name == "work"
    assert settings.text_layer_min_chars == 20
    assert settings.ocr_language == "ita"
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_settings_derived_paths_use_base_dir(tmp_path):
    settings = Settings(base_dir=tmp_path)
    assert settings.input_dir == tmp_path / "input"
    assert settings.processed_dir == tmp_path / "processed"
    assert settings.error_dir == tmp_path / "error"
    assert settings.logs_dir == tmp_path / "logs"
    assert settings.export_dir == tmp_path / "export"
    assert settings.work_dir == tmp_path / "work"


def test_settings_accepts_python_names_for_aliased_fields(tmp_path):
    settings = Settings(base_dir=tmp_path, database_url="******host:5432/db")
    assert settings.base_dir == tmp_path
    assert settings.database_url == "******host:5432/db"


def test_settings_ensure_folders_creates_all_dirs(tmp_path):
    settings = Settings(PAYROLL_BASE_DIR=tmp_path / "root")
    settings.ensure_folders()

    assert settings.input_dir.is_dir()
    assert settings.processed_dir.is_dir()
    assert settings.error_dir.is_dir()
    assert settings.logs_dir.is_dir()
    assert settings.export_dir.is_dir()
    assert settings.work_dir.is_dir()


def test_settings_ensure_folders_idempotent(tmp_path):
    settings = Settings(PAYROLL_BASE_DIR=tmp_path)
    settings.ensure_folders()
    settings.ensure_folders()  # non deve sollevare se le cartelle esistono gia'
    assert settings.input_dir.is_dir()


def test_settings_reads_env_vars_via_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@host:5432/db")
    monkeypatch.setenv("PAYROLL_BASE_DIR", str(tmp_path))
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://x:y@host:5432/db"
    assert settings.base_dir == tmp_path


def test_get_settings_returns_settings_instance():
    settings = get_settings()
    assert isinstance(settings, Settings)
