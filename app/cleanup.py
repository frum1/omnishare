import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.database import async_session_maker
from app.models import FileShare

logger = logging.getLogger("hshare.cleanup")


async def purge_expired_files() -> int:
    """Удаляет истёкшие по TTL файлы с диска и из БД. Возвращает число удалённых."""
    now = datetime.utcnow()
    removed = 0
    async with async_session_maker() as session:
        result = await session.execute(select(FileShare).where(FileShare.expires_at.is_not(None), FileShare.expires_at < now))
        expired = result.scalars().all()
        for file_share in expired:
            Path(file_share.stored_path).unlink(missing_ok=True)
            await session.delete(file_share)
            removed += 1
        if removed:
            await session.commit()
    if removed:
        logger.info("Purged %d expired file(s)", removed)
    return removed
