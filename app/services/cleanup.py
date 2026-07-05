import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.core.storage import build_incomplete_path, cleanup_empty_parents
from app.db.models import FileShare, TusUpload
from app.db.session import async_session_maker

logger = logging.getLogger("omnishare.cleanup")


async def purge_expired_files() -> int:
    now = datetime.utcnow()
    removed = 0
    async with async_session_maker() as session:
        result = await session.execute(select(FileShare).where(FileShare.expires_at.is_not(None), FileShare.expires_at < now))
        expired = result.scalars().all()
        for file_share in expired:
            stored_path = Path(file_share.stored_path)
            stored_path.unlink(missing_ok=True)
            cleanup_empty_parents(stored_path)
            await session.delete(file_share)
            removed += 1
        if removed:
            await session.commit()
    if removed:
        logger.info("Purged %d expired file(s)", removed)
    return removed


async def purge_stale_uploads() -> int:
    """Drop resumable uploads that were started but never finished within the
    configured window, along with their partial files on disk."""
    now = datetime.utcnow()
    removed = 0
    async with async_session_maker() as session:
        result = await session.execute(select(TusUpload).where(TusUpload.expires_at < now))
        stale = result.scalars().all()
        for upload in stale:
            build_incomplete_path(upload.id).unlink(missing_ok=True)
            await session.delete(upload)
            removed += 1
        if removed:
            await session.commit()
    if removed:
        logger.info("Purged %d stale upload(s)", removed)
    return removed
