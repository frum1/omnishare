from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import FileShare

router = APIRouter(tags=["download"])


@router.get("/f/{file_id}")
async def download_file(file_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    now = datetime.utcnow()
    expired_by_ttl = file_share.expires_at is not None and file_share.expires_at < now
    expired_by_limit = (
        file_share.max_downloads is not None and file_share.download_count >= file_share.max_downloads
    )
    if expired_by_ttl or expired_by_limit:
        Path(file_share.stored_path).unlink(missing_ok=True)
        await db.delete(file_share)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Срок действия ссылки истёк")

    path = Path(file_share.stored_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    file_share.download_count += 1
    await db.commit()

    return FileResponse(
        path=path,
        media_type=file_share.content_type,
        filename=file_share.original_filename,
    )
