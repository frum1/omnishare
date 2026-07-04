import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.network import build_share_urls
from app.core.security import get_current_active_user, get_current_admin
from app.core.storage import build_storage_path, cleanup_empty_parents
from app.db.models import FileShare, User
from app.db.session import get_db
from app.schemas import DiskUsageOut, FileCaptionUpdate, FileOut, UserUsageOut
from app.services.quota import get_usage_bytes

router = APIRouter(prefix="/api/files", tags=["files"])


def _file_out(file_share: FileShare) -> FileOut:
    urls = build_share_urls(file_share.id)
    return FileOut(
        id=file_share.id,
        original_filename=file_share.original_filename,
        content_type=file_share.content_type,
        size_bytes=file_share.size_bytes,
        caption=file_share.caption,
        created_at=file_share.created_at,
        expires_at=file_share.expires_at,
        max_downloads=file_share.max_downloads,
        download_count=file_share.download_count,
        public_url=urls["public_url"],
        local_url=urls["local_url"],
    )


async def _save_upload(upload: UploadFile, dest: Path, quota_remaining: int | None) -> int:
    total = 0
    max_size = settings.max_file_size_bytes
    chunk_size = settings.upload_chunk_size_bytes
    try:
        async with aiofiles.open(dest, "wb") as out:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds the maximum size of {settings.max_file_size_mb} MB",
                    )
                if quota_remaining is not None and total > quota_remaining:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Upload exceeds your storage quota",
                    )
                await out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return total


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    ttl_seconds: int | None = Form(None),
    max_downloads: int | None = Form(None),
    caption: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    quota_remaining = None
    if current_user.quota_bytes is not None:
        used_bytes = await get_usage_bytes(db, current_user.id)
        quota_remaining = current_user.quota_bytes - used_bytes
        if quota_remaining <= 0:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Storage quota exceeded",
            )

    file_id = uuid.uuid4().hex
    created_at = datetime.utcnow()
    dest = build_storage_path(file_id, created_at)
    dest.parent.mkdir(parents=True, exist_ok=True)
    size_bytes = await _save_upload(file, dest, quota_remaining)

    # 0 or None means "infinite" - convenient for forms where the field is
    # always present and defaults to 0.
    expires_at = None
    if ttl_seconds is not None:
        if ttl_seconds < 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="ttl_seconds cannot be negative")
        if ttl_seconds > 0:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

    if max_downloads is not None:
        if max_downloads < 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="max_downloads cannot be negative")
        if max_downloads == 0:
            max_downloads = None

    caption = caption.strip() if caption and caption.strip() else None

    file_share = FileShare(
        id=file_id,
        owner_id=current_user.id,
        original_filename=file.filename or file_id,
        stored_path=str(dest),
        content_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
        caption=caption,
        created_at=created_at,
        expires_at=expires_at,
        max_downloads=max_downloads,
    )
    db.add(file_share)
    await db.commit()
    await db.refresh(file_share)

    return _file_out(file_share)


@router.get("/disk-usage", response_model=DiskUsageOut)
async def get_disk_usage(
    _: User = Depends(get_current_admin),
):
    total, used, free = shutil.disk_usage(settings.storage_path)
    return DiskUsageOut(total_bytes=total, used_bytes=used, free_bytes=free)


@router.get("/usage", response_model=UserUsageOut)
async def get_my_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    used_bytes = await get_usage_bytes(db, current_user.id)
    return UserUsageOut(used_bytes=used_bytes, quota_bytes=current_user.quota_bytes)


@router.get("")
async def list_files(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.is_admin:
        result = await db.execute(select(FileShare).order_by(FileShare.owner_id, FileShare.created_at.desc()))
        grouped: dict[str, list[FileOut]] = {}
        for file_share in result.scalars().all():
            grouped.setdefault(file_share.owner_id, []).append(_file_out(file_share))
        return grouped

    result = await db.execute(
        select(FileShare).where(FileShare.owner_id == current_user.id).order_by(FileShare.created_at.desc())
    )
    return [_file_out(f) for f in result.scalars().all()]


@router.get("/{file_id}/info", response_model=FileOut)
async def get_file_info(
    file_id: str,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    return _file_out(file_share)


@router.patch("/{file_id}", response_model=FileOut)
async def update_file_caption(
    file_id: str,
    payload: FileCaptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if file_share.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this file")

    file_share.caption = payload.caption.strip() if payload.caption and payload.caption.strip() else None
    await db.commit()
    await db.refresh(file_share)
    return _file_out(file_share)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if file_share.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this file")

    stored_path = Path(file_share.stored_path)
    stored_path.unlink(missing_ok=True)
    cleanup_empty_parents(stored_path)
    await db.delete(file_share)
    await db.commit()
