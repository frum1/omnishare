import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_admin, hash_password
from app.core.storage import cleanup_empty_parents
from app.db.models import FileShare, User
from app.db.session import get_db
from app.schemas import PasswordResetOut, QuotaUpdate, UserCreate, UserOut
from app.services.quota import build_user_out, build_user_out_with_usage, get_usage_by_user

router = APIRouter(prefix="/admin/users", tags=["users"])


async def _get_user_or_404(user_id: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    existing = await db.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")

    if payload.quota_bytes is not None and payload.quota_bytes < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quota_bytes cannot be negative")

    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        is_admin=payload.is_admin,
        quota_bytes=payload.quota_bytes,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return build_user_out(user, used_bytes=0)


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    usage = await get_usage_by_user(db)
    return [build_user_out(user, usage.get(user.id, 0)) for user in users]


@router.patch("/{user_id}/quota", response_model=UserOut)
async def update_user_quota(
    user_id: str,
    payload: QuotaUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    user = await _get_user_or_404(user_id, db)

    if payload.quota_bytes is not None and payload.quota_bytes < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quota_bytes cannot be negative")

    user.quota_bytes = payload.quota_bytes
    await db.commit()
    await db.refresh(user)
    return await build_user_out_with_usage(db, user)


@router.post("/{user_id}/reset-password", response_model=PasswordResetOut)
async def reset_password(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    user = await _get_user_or_404(user_id, db)

    temporary_password = secrets.token_urlsafe(12)
    user.hashed_password = hash_password(temporary_password)
    user.must_change_password = True
    await db.commit()

    return PasswordResetOut(username=user.username, temporary_password=temporary_password)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    if user_id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account")

    user = await _get_user_or_404(user_id, db)

    files = await db.execute(select(FileShare).where(FileShare.owner_id == user.id))
    for file_share in files.scalars().all():
        stored_path = Path(file_share.stored_path)
        stored_path.unlink(missing_ok=True)
        cleanup_empty_parents(stored_path)
        await db.delete(file_share)

    await db.delete(user)
    await db.commit()
