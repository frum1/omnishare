import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cleanup import purge_expired_files
from app.config import settings
from app.database import init_db
from app.routers import auth, download, files, settings as settings_router, users


async def _cleanup_loop():
    while True:
        # интервал читается заново на каждой итерации, чтобы изменения через
        # POST /admin/settings подхватывались без перезапуска сервиса
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)
        await purge_expired_files()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
