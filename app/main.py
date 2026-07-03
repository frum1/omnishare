import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.db.session import init_db
from app.routers import auth, download, files, settings as settings_router, users
from app.services.bootstrap import ensure_root_admin
from app.services.cleanup import purge_expired_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _cleanup_loop():
    while True:
        # interval is re-read every iteration so changes made via
        # POST /admin/settings take effect without restarting the service
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)
        await purge_expired_files()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_root_admin()
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="hshare", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(settings_router.router)
app.include_router(files.router)
app.include_router(download.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
