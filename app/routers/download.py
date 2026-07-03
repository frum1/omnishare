import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.core.storage import cleanup_empty_parents
from app.db.models import FileShare
from app.db.session import async_session_maker, get_db

logger = logging.getLogger("omnishare.download")

router = APIRouter(tags=["download"])


async def _delete_after_last_download(file_id: str) -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(FileShare).where(FileShare.id == file_id))
        file_share = result.scalar_one_or_none()
        if file_share is None:
            return
        stored_path = Path(file_share.stored_path)
        stored_path.unlink(missing_ok=True)
        cleanup_empty_parents(stored_path)
        await session.delete(file_share)
        await session.commit()
    logger.info("Deleted file %s (download limit reached)", file_id)


@router.get("/f/{file_id}")
async def download_file(file_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    now = datetime.utcnow()
    expired_by_ttl = file_share.expires_at is not None and file_share.expires_at < now
    expired_by_limit = (
        file_share.max_downloads is not None and file_share.download_count >= file_share.max_downloads
    )
    if expired_by_ttl or expired_by_limit:
        stored_path = Path(file_share.stored_path)
        stored_path.unlink(missing_ok=True)
        cleanup_empty_parents(stored_path)
        await db.delete(file_share)
        await db.commit()
        reason = "ttl" if expired_by_ttl else "download limit"
        logger.info("Deleted expired file %s (%s) on access", file_share.id, reason)
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This link has expired")

    path = Path(file_share.stored_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    file_share.download_count += 1
    reached_limit = (
        file_share.max_downloads is not None and file_share.download_count >= file_share.max_downloads
    )
    await db.commit()

    return FileResponse(
        path=path,
        media_type=file_share.content_type,
        filename=file_share.original_filename,
        background=BackgroundTask(_delete_after_last_download, file_share.id) if reached_limit else None,
    )
