from datetime import datetime

from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = True
    quota_bytes: int | None = None


class UserOut(BaseModel):
    id: str
    username: str
    is_admin: bool
    must_change_password: bool
    created_at: datetime
    quota_bytes: int | None
    used_bytes: int


class QuotaUpdate(BaseModel):
    quota_bytes: int | None


class UserUsageOut(BaseModel):
    used_bytes: int
    quota_bytes: int | None


class PasswordResetOut(BaseModel):
    username: str
    temporary_password: str


class ChangePasswordIn(BaseModel):
    new_password: str


class FileOut(BaseModel):
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    caption: str | None
    created_at: datetime
    expires_at: datetime | None
    max_downloads: int | None
    download_count: int
    public_url: str
    local_url: str


class FileInfoUpdate(BaseModel):
    """Partial update of an existing file's share settings. Only the fields
    actually present in the request body are applied, so omitting one leaves it
    unchanged (whereas sending it as ``null`` clears it — no expiry / no limit)."""

    caption: str | None = None
    expires_at: datetime | None = None
    max_downloads: int | None = None


class DiskUsageOut(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int


class NetworkSettingsOut(BaseModel):
    public_base_url: str
    local_base_url: str
    local_port: int
    local_mode: bool
    max_file_size_mb: int
    cleanup_interval_minutes: int


class NetworkSettingsUpdate(BaseModel):
    public_base_url: str | None = None
    local_base_url: str | None = None
    local_port: int | None = None
    local_mode: bool | None = None
    max_file_size_mb: int | None = None
    cleanup_interval_minutes: int | None = None
