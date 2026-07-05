"""Shared upload semantics used by both the multipart endpoint and the
resumable (TUS) endpoint, so a file ends up with identical quota accounting,
expiry and share settings regardless of how its bytes arrived."""

from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FileShare, User
from app.services.quota import get_usage_bytes


async def get_quota_remaining(db: AsyncSession, user: User) -> int | None:
    """Bytes the user may still store, or None when the quota is unlimited.

    Raises 413 when the quota is already fully consumed, so callers can bail
    out before touching disk.
    """
    if user.quota_bytes is None:
        return None
    remaining = user.quota_bytes - await get_usage_bytes(db, user.id)
    if remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Storage quota exceeded",
        )
    return remaining


def resolve_expires_at(ttl_seconds: int | None, created_at: datetime) -> datetime | None:
    """0 or None means "never expires"."""
    if ttl_seconds and ttl_seconds > 0:
        return created_at + timedelta(seconds=ttl_seconds)
    return None


def normalize_max_downloads(max_downloads: int | None) -> int | None:
    """0 or None means "unlimited"."""
    return max_downloads if max_downloads and max_downloads > 0 else None


def normalize_caption(caption: str | None) -> str | None:
    return caption.strip() if caption and caption.strip() else None


def build_file_share(
    *,
    file_id: str,
    owner_id: str,
    original_filename: str,
    stored_path: str,
    content_type: str,
    size_bytes: int,
    caption: str | None,
    created_at: datetime,
    ttl_seconds: int | None,
    max_downloads: int | None,
) -> FileShare:
    """Single place that turns a finished upload into a FileShare row, applying
    the shared expiry / download-limit / caption normalization rules."""
    return FileShare(
        id=file_id,
        owner_id=owner_id,
        original_filename=original_filename,
        stored_path=stored_path,
        content_type=content_type,
        size_bytes=size_bytes,
        caption=normalize_caption(caption),
        created_at=created_at,
        expires_at=resolve_expires_at(ttl_seconds, created_at),
        max_downloads=normalize_max_downloads(max_downloads),
    )
