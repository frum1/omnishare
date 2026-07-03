from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    public_base_url: str = "http://localhost:8000"
    local_base_url: str = ""
    local_port: int = 8000

    secret_key: str = "changeme"
    access_token_expire_minutes: int = 60 * 24
    jwt_algorithm: str = "HS256"

    database_url: str = "sqlite+aiosqlite:///./data/hshare.db"
    storage_dir: str = "./storage"

    max_file_size_mb: int = 1024
    upload_chunk_size_kb: int = 1024

    cleanup_interval_minutes: int = 30

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def upload_chunk_size_bytes(self) -> int:
        return self.upload_chunk_size_kb * 1024

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
