import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow)
    # None means unlimited - the default for every user, admins included.
    quota_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    files: Mapped[list["FileShare"]] = relationship(back_populates="owner")


class FileShare(Base):
    __tablename__ = "file_shares"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str | None] = mapped_column(Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    max_downloads: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, default=0)

    owner: Mapped["User"] = relationship(back_populates="files")


class TusUpload(Base):
    """Metadata for a resumable (TUS) upload in progress.

    The current offset is not stored here - it is always read from the size of
    the on-disk partial file, which stays authoritative across restarts. This
    row only carries what is needed to create the FileShare once the transfer
    completes, plus an expiry so abandoned uploads can be swept.
    """

    __tablename__ = "tus_uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    upload_length: Mapped[int] = mapped_column(Integer)
    caption: Mapped[str | None] = mapped_column(Text(), nullable=True)
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_downloads: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
