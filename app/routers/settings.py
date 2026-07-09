from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.core.env_file import update_env_file
from app.core.security import get_current_active_user, get_current_admin
from app.db.models import User
from app.schemas import NetworkSettingsOut, NetworkSettingsUpdate

router = APIRouter(prefix="/api/admin/settings", tags=["settings"])

# Endpoints any authenticated user may reach (not just admins).
public_router = APIRouter(prefix="/api", tags=["settings"])


def _current() -> NetworkSettingsOut:
    return NetworkSettingsOut(
        public_base_url=settings.public_base_url,
        local_base_url=settings.local_base_url,
        local_port=settings.local_port,
        local_mode=settings.local_mode,
        max_file_size_mb=settings.max_file_size_mb,
        cleanup_interval_minutes=settings.cleanup_interval_minutes,
    )


@public_router.get("/local-mode-available", response_model=bool)
async def local_mode_available(_: User = Depends(get_current_active_user)) -> bool:
    """Whether local-network share links are enabled, for the current user."""
    return settings.local_mode


@router.get("", response_model=NetworkSettingsOut)
async def get_settings(_: User = Depends(get_current_admin)):
    return _current()


@router.post("", response_model=NetworkSettingsOut)
async def update_settings(
    payload: NetworkSettingsUpdate,
    _: User = Depends(get_current_admin),
):
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)

    if "public_base_url" in updates and not updates["public_base_url"].strip():
        raise HTTPException(status_code=400, detail="public_base_url cannot be empty")
    if "local_port" in updates and not (1 <= updates["local_port"] <= 65535):
        raise HTTPException(status_code=400, detail="local_port must be in range 1-65535")
    if "max_file_size_mb" in updates and updates["max_file_size_mb"] <= 0:
        raise HTTPException(status_code=400, detail="max_file_size_mb must be positive")
    if "cleanup_interval_minutes" in updates and updates["cleanup_interval_minutes"] < 1:
        raise HTTPException(status_code=400, detail="cleanup_interval_minutes must be at least 1")

    for field, value in updates.items():
        setattr(settings, field, value)

    if updates:
        update_env_file({field.upper(): str(value) for field, value in updates.items()})

    return _current()
