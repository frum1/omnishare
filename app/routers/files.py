import base64
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.network import build_share_urls
from app.core.security import get_current_active_user, get_current_admin
from app.core.storage import build_incomplete_path, build_storage_path, cleanup_empty_parents
from app.db.models import FileShare, TusUpload, User
from app.db.session import get_db
from app.schemas import DiskUsageOut, FileInfoUpdate, FileOut, UserUsageOut
from app.services.quota import get_usage_bytes
from app.services.uploads import (
    build_file_share,
    get_quota_remaining,
    normalize_caption,
    normalize_max_downloads,
)

TUS_VERSION = "1.0.0"
PATCH_CONTENT_TYPE = "application/offset+octet-stream"

router = APIRouter(prefix="/api/files", tags=["files"])


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize an incoming datetime to naive UTC so it lines up with the
    naive ``datetime.utcnow()`` timestamps the rest of the app stores and
    compares against (e.g. the expiry cleanup)."""
    if dt is not None and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


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


# --------------------------------------------------------------------------- #
# TUS helpers
# --------------------------------------------------------------------------- #

def _tus_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Tus-Resumable": TUS_VERSION}
    if extra:
        headers.update(extra)
    return headers


async def require_tus_version(tus_resumable: str | None = Header(None)) -> None:
    """Reject requests that declare a TUS version we do not speak.

    The header is optional (a missing one is treated as compatible, so plain
    REST calls like a caption PATCH still work) but when present it must match.
    """
    if tus_resumable is not None and tus_resumable != TUS_VERSION:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Unsupported TUS version",
            headers=_tus_headers({"Tus-Version": TUS_VERSION}),
        )


def _parse_metadata(raw: str | None) -> dict[str, str]:
    """Decode the Upload-Metadata header: comma-separated ``key <base64>`` pairs.

    A pair may carry a key with no value; such keys map to an empty string.
    Malformed base64 is tolerated (mapped to empty) rather than failing the
    whole upload over one bad field.
    """
    meta: dict[str, str] = {}
    if not raw:
        return meta
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        parts = pair.split(" ", 1)
        key = parts[0]
        if len(parts) == 2:
            try:
                meta[key] = base64.b64decode(parts[1]).decode("utf-8")
            except Exception:
                meta[key] = ""
        else:
            meta[key] = ""
    return meta


def _meta_positive_int(meta: dict[str, str], key: str) -> int | None:
    """Read an optional positive integer field; 0 / absent / invalid -> None."""
    raw = meta.get(key)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


async def _owned_upload(uid: str, db: AsyncSession, user: User) -> TusUpload | None:
    upload = await db.get(TusUpload, uid)
    if upload is None:
        return None
    if upload.owner_id != user.id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this upload",
            headers=_tus_headers(),
        )
    return upload


async def _finalize(upload: TusUpload, db: AsyncSession) -> None:
    """Promote a completed partial file into a shared FileShare and drop the
    in-progress record."""
    created_at = datetime.utcnow()
    dest = build_storage_path(upload.id, created_at)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # incomplete/ lives under storage_path, so this is a same-filesystem rename.
    build_incomplete_path(upload.id).rename(dest)

    db.add(
        build_file_share(
            file_id=upload.id,
            owner_id=upload.owner_id,
            original_filename=upload.original_filename,
            stored_path=str(dest),
            content_type=upload.content_type,
            size_bytes=upload.upload_length,
            caption=upload.caption,
            created_at=created_at,
            ttl_seconds=upload.ttl_seconds,
            max_downloads=upload.max_downloads,
        )
    )
    await db.delete(upload)
    await db.commit()


# --------------------------------------------------------------------------- #
# Upload (TUS): create / resume / append
# --------------------------------------------------------------------------- #

@router.options("")
async def upload_capabilities() -> Response:
    """Advertise protocol version, extensions and the size ceiling. No auth:
    this is a capability probe issued before authenticating a creation POST."""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers=_tus_headers(
            {
                "Tus-Version": TUS_VERSION,
                "Tus-Extension": "creation,termination",
                "Tus-Max-Size": str(settings.max_file_size_bytes),
            }
        ),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_upload(
    request: Request,
    upload_length: int | None = Header(None),
    upload_metadata: str | None = Header(None),
    upload_defer_length: int | None = Header(None),
    _: None = Depends(require_tus_version),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """TUS creation: reserve an upload and return its item URL in Location."""
    if upload_defer_length is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deferred length is not supported; send Upload-Length",
            headers=_tus_headers(),
        )
    if upload_length is None or upload_length < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A non-negative Upload-Length header is required",
            headers=_tus_headers(),
        )
    if upload_length > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the maximum size of {settings.max_file_size_mb} MB",
            headers=_tus_headers(),
        )

    # Reserve the declared size against the quota up front, so an oversized
    # upload is refused before a single byte is transferred.
    quota_remaining = await get_quota_remaining(db, current_user)
    if quota_remaining is not None and upload_length > quota_remaining:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Upload exceeds your storage quota",
            headers=_tus_headers(),
        )

    meta = _parse_metadata(upload_metadata)
    filename = meta.get("filename") or meta.get("name")
    content_type = meta.get("filetype") or meta.get("content_type") or "application/octet-stream"

    now = datetime.utcnow()
    upload = TusUpload(
        owner_id=current_user.id,
        original_filename=filename or "unnamed",
        content_type=content_type,
        upload_length=upload_length,
        caption=normalize_caption(meta.get("caption")),
        ttl_seconds=_meta_positive_int(meta, "ttl"),
        max_downloads=_meta_positive_int(meta, "maxdownloads"),
        created_at=now,
        expires_at=now + timedelta(hours=settings.incomplete_upload_ttl_hours),
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)

    # Create the (empty) partial file so HEAD/PATCH have something to stat.
    build_incomplete_path(upload.id).touch()

    # A zero-length upload is already complete on creation.
    if upload_length == 0:
        await _finalize(upload, db)

    location = str(request.url_for("file_item", file_id=upload.id))
    return Response(
        status_code=status.HTTP_201_CREATED,
        headers=_tus_headers({"Location": location, "Upload-Offset": "0"}),
    )


async def _append_chunk(
    file_id: str,
    request: Request,
    upload_offset: int | None,
    db: AsyncSession,
    current_user: User,
) -> Response:
    """TUS PATCH: append the request body at the given offset."""
    if upload_offset is None or upload_offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A non-negative Upload-Offset header is required",
            headers=_tus_headers(),
        )

    upload = await _owned_upload(file_id, db, current_user)
    path = build_incomplete_path(file_id)
    if upload is None or not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
            headers=_tus_headers(),
        )

    current = path.stat().st_size
    if upload_offset != current:
        # The client's idea of the offset diverged from ours; hand back the
        # authoritative value so it can resume from the right place.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload-Offset does not match the stored offset",
            headers=_tus_headers({"Upload-Offset": str(current)}),
        )

    total = upload.upload_length
    with path.open("ab") as f:
        async for chunk in request.stream():
            f.write(chunk)
            if f.tell() > total:
                # Roll back this over-long PATCH so the upload stays resumable.
                f.truncate(current)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Upload exceeds the declared Upload-Length",
                    headers=_tus_headers({"Upload-Offset": str(current)}),
                )

    new_offset = path.stat().st_size
    if new_offset == total:
        await _finalize(upload, db)

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers=_tus_headers({"Upload-Offset": str(new_offset)}),
    )


# --------------------------------------------------------------------------- #
# Listing / usage (fixed sub-paths, must precede /{file_id})
# --------------------------------------------------------------------------- #

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


@router.patch("/{file_id}/info", status_code=status.HTTP_204_NO_CONTENT)
async def update_file_info(
    file_id: str,
    payload: FileInfoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Update the share settings (caption / expiry / download limit) of a
    finished file.

    Only the fields present in the body are touched, so changing one leaves the
    others as-is. Responds 204 on success.
    """
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if file_share.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this file")

    fields = payload.model_fields_set
    if "caption" in fields:
        file_share.caption = normalize_caption(payload.caption)
    if "expires_at" in fields:
        file_share.expires_at = _to_naive_utc(payload.expires_at)
    if "max_downloads" in fields:
        file_share.max_downloads = normalize_max_downloads(payload.max_downloads)

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Item URL: serves both the in-progress upload and the finished file
# --------------------------------------------------------------------------- #

@router.head("/{file_id}", name="file_item")
async def head_file(
    file_id: str,
    _: None = Depends(require_tus_version),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """TUS HEAD: report the resume offset of an in-progress upload, or the full
    length of an already-completed file."""
    upload = await _owned_upload(file_id, db, current_user)
    if upload is not None:
        path = build_incomplete_path(file_id)
        offset = path.stat().st_size if path.exists() else 0
        return Response(
            status_code=status.HTTP_200_OK,
            headers=_tus_headers(
                {
                    "Upload-Offset": str(offset),
                    "Upload-Length": str(upload.upload_length),
                    "Cache-Control": "no-store",
                }
            ),
        )

    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is not None:
        return Response(
            status_code=status.HTTP_200_OK,
            headers=_tus_headers(
                {
                    "Upload-Offset": str(file_share.size_bytes),
                    "Upload-Length": str(file_share.size_bytes),
                    "Cache-Control": "no-store",
                }
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Not found",
        headers=_tus_headers(),
    )


@router.patch("/{file_id}")
async def patch_file(
    file_id: str,
    request: Request,
    upload_offset: int | None = Header(None),
    content_type: str | None = Header(None),
    _: None = Depends(require_tus_version),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Two operations behind one verb, dispatched on Content-Type:

    * ``application/offset+octet-stream`` -> TUS append (in-progress upload)
    * anything else (JSON) -> update the caption of a finished file

    Expiry / download-limit changes live on ``PATCH /{file_id}/info``.
    """
    if content_type == PATCH_CONTENT_TYPE:
        return await _append_chunk(file_id, request, upload_offset, db, current_user)

    # Caption update on a finished FileShare.
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if file_share.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this file")

    file_share.caption = normalize_caption(body.get("caption"))
    await db.commit()
    await db.refresh(file_share)
    return _file_out(file_share)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    _: None = Depends(require_tus_version),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Delete a finished file, or (TUS termination) abandon an in-progress
    upload - whichever the id refers to."""
    result = await db.execute(select(FileShare).where(FileShare.id == file_id))
    file_share = result.scalar_one_or_none()
    if file_share is not None:
        if file_share.owner_id != current_user.id and not current_user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this file")
        stored_path = Path(file_share.stored_path)
        stored_path.unlink(missing_ok=True)
        cleanup_empty_parents(stored_path)
        await db.delete(file_share)
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_tus_headers())

    upload = await _owned_upload(file_id, db, current_user)
    if upload is not None:
        build_incomplete_path(file_id).unlink(missing_ok=True)
        await db.delete(upload)
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_tus_headers())

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Not found",
        headers=_tus_headers(),
    )
