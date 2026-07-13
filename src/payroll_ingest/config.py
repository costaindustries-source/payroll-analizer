from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://payroll:payroll@localhost:5432/payroll",
        alias="DATABASE_URL",
    )

    base_dir: Path = Field(default=Path("."), alias="PAYROLL_BASE_DIR")

    input_dir_name: str = "input"
    processed_dir_name: str = "processed"
    error_dir_name: str = "error"
    logs_dir_name: str = "logs"
    export_dir_name: str = "export"
    work_dir_name: str = "work"

    text_layer_min_chars: int = Field(
        default=20,
        description="Sotto questa soglia di caratteri estratti dalla pagina si considera il PDF scansionato (serve OCR).",
    )
    ocr_language: str = "ita"

    @property
    def input_dir(self) -> Path:
        return self.base_dir / self.input_dir_name

    @property
    def processed_dir(self) -> Path:
        return self.base_dir / self.processed_dir_name

    @property
    def error_dir(self) -> Path:
        return self.base_dir / self.error_dir_name

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / self.logs_dir_name

    @property
    def export_dir(self) -> Path:
        return self.base_dir / self.export_dir_name

    @property
    def work_dir(self) -> Path:
        return self.base_dir / self.work_dir_name

    def ensure_folders(self) -> None:
        for d in (
            self.input_dir,
            self.processed_dir,
            self.error_dir,
            self.logs_dir,
            self.export_dir,
            self.work_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
