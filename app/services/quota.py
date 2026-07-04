from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FileShare, User
from app.schemas import UserOut


async def get_usage_bytes(db: AsyncSession, user_id: str) -> int:
    result = await db.execute(select(func.sum(FileShare.size_bytes)).where(FileShare.owner_id == user_id))
    return result.scalar() or 0


async def get_usage_by_user(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(select(FileShare.owner_id, func.sum(FileShare.size_bytes)).group_by(FileShare.owner_id))
    return {owner_id: total or 0 for owner_id, total in result.all()}


def build_user_out(user: User, used_bytes: int) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
        quota_bytes=user.quota_bytes,
        used_bytes=used_bytes,
    )


async def build_user_out_with_usage(db: AsyncSession, user: User) -> UserOut:
    return build_user_out(user, await get_usage_bytes(db, user.id))
