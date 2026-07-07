import secrets
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": .env is shared with docker-compose's other services
    # (e.g. DOMAIN for Caddy), so it may carry keys this app doesn't declare.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    public_base_url: str = "http://localhost:8000"
    local_base_url: str = ""
    local_port: int = 8000
    # When enabled, clients on the local network may use the local share links.
    local_mode: bool = False

    # Left empty to auto-generate: a random key is created on first boot and
    # persisted (see _resolve_secret_key). Set it explicitly only to pin a key
    # across separate instances that must share JWTs.
    secret_key: str = ""
    access_token_expire_minutes: int = 60 * 24
    jwt_algorithm: str = "HS256"

    database_url: str = "sqlite+aiosqlite:///./data/omnishare.db"
    storage_dir: str = "./storage"

    max_file_size_mb: int = 1024
    upload_chunk_size_kb: int = 1024

    cleanup_interval_minutes: int = 30
    # Resumable (TUS) uploads that never finish are dropped after this window.
    incomplete_upload_ttl_hours: int = 24

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

    @property
    def incomplete_path(self) -> Path:
        """Flat directory holding partially-uploaded TUS files until they are
        finalized and moved into the sharded storage tree."""
        path = self.storage_path / "incomplete"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @model_validator(mode="after")
    def _resolve_secret_key(self) -> "Settings":
        """Ensure a stable JWT signing key without a manual setup step.

        An explicit SECRET_KEY (from env/.env) always wins. Otherwise a random
        key is generated once and persisted to data/secret_key so it survives
        restarts — invalidating it would log everyone out on every reboot.
        """
        if self.secret_key and self.secret_key != "changeme":
            return self
        key_path = Path("data") / "secret_key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            self.secret_key = key_path.read_text().strip()
        else:
            self.secret_key = secrets.token_hex(32)
            key_path.write_text(self.secret_key + "\n")
            key_path.chmod(0o600)
        return self


settings = Settings()
