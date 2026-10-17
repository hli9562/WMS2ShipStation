from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WMS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    shipstation_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="SHIPSTATION_API_KEY"
    )
    shipstation_api_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias="SHIPSTATION_API_SECRET"
    )
    enable_live_purchase: bool = False

    data_dir: Path = Path("data")
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    max_upload_bytes: int = 10 * 1024 * 1024
    max_uncompressed_bytes: int = 100 * 1024 * 1024
    max_sheet_rows: int = 1000

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir.resolve() / 'app.sqlite3'}"

    @property
    def labels_dir(self) -> Path:
        return self.data_dir / "labels"
