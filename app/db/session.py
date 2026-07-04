from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

if settings.database_url.startswith("sqlite"):
    db_file = settings.database_url.split("///")[-1]
    Path(db_file).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.database_url, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # create_all only adds missing tables, not missing columns on tables
        # that already existed - patch the pre-quota schema in place here
        # since there's no migration framework in this project.
        if settings.database_url.startswith("sqlite"):
            result = await conn.execute(text("PRAGMA table_info(users)"))
            columns = {row[1] for row in result.fetchall()}
            if "quota_bytes" not in columns:
                await conn.execute(text("ALTER TABLE users ADD COLUMN quota_bytes INTEGER"))


async def get_db():
    async with async_session_maker() as session:
        yield session
