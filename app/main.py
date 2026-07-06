import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"
from app.db.session import init_db
from app.routers import auth, download, files, settings as settings_router, users
from app.services.bootstrap import ensure_root_admin
from app.services.cleanup import purge_expired_files, purge_stale_uploads

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _cleanup_loop():
    while True:
        # interval is re-read every iteration so changes made via
        # POST /admin/settings take effect without restarting the service
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)
        await purge_expired_files()
        await purge_stale_uploads()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_root_admin()
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="OmniShare", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(settings_router.router)
app.include_router(settings_router.public_router)
app.include_router(files.router)
app.include_router(download.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

DIST_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    candidate = DIST_DIR / full_path
    if full_path and Path(candidate).is_file():
        return FileResponse(candidate)
    return FileResponse(DIST_DIR / "index.html")
