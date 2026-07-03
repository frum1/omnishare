from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = True


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    is_admin: bool
    created_at: datetime


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


class FileCaptionUpdate(BaseModel):
    caption: str | None


class NetworkSettingsOut(BaseModel):
    public_base_url: str
    local_base_url: str
    local_port: int
    max_file_size_mb: int
    cleanup_interval_minutes: int


class NetworkSettingsUpdate(BaseModel):
    public_base_url: str | None = None
    local_base_url: str | None = None
    local_port: int | None = None
    max_file_size_mb: int | None = None
    cleanup_interval_minutes: int | None = None
