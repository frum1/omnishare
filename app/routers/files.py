import uuid
from datetime import datetime, timedelta
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.network import build_share_urls
from app.core.security import get_current_user
from app.db.models import FileShare, User
from app.db.session import get_db
from app.schemas import FileCaptionUpdate, FileOut

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


async def _save_upload(upload: UploadFile, dest: Path) -> int:
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
                        detail=f"Файл превышает максимальный размер {settings.max_file_size_mb} МБ",
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
    current_user: User = Depends(get_current_user),
):
    file_id = uuid.uuid4().hex
    dest = settings.storage_path / file_id
    size_bytes = await _save_upload(file, dest)

    # 0 или None означает "бесконечно" - удобно для форм, где поле всегда
    # присутствует и по умолчанию равно 0.
    expires_at = None
    if ttl_seconds is not None:
        if ttl_seconds < 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="ttl_seconds не может быть отрицательным")
        if ttl_seconds > 0:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

    if max_downloads is not None:
        if max_downloads < 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="max_downloads не может быть отрицательным")
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
        expires_at=expires_at,
        max_downloads=max_downloads,
    )
    db.add(file_share)
    await db.commit()
    await db.refresh(file_share)

    return _file_out(file_share)


@router.get("")
async def list_files(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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


@router.patch("/{file_id}", response_model=FileOut)
async def update_file_caption(
    file_id: str,
    payload: FileCaptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    if file_share.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к этому файлу")

    file_share.caption = payload.caption.strip() if payload.caption and payload.caption.strip() else None
    await db.commit()
    await db.refresh(file_share)
    return _file_out(file_share)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    if file_share.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к этому файлу")

    Path(file_share.stored_path).unlink(missing_ok=True)
    await db.delete(file_share)
    await db.commit()
