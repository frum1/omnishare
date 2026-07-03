import secrets

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import User
from app.db.session import async_session_maker

ROOT_ADMIN_USERNAME = "admin"


async def ensure_root_admin() -> None:
    """Creates the root admin account on first boot if it doesn't exist yet.

    Renaming or deleting the "admin" user doesn't lock you out permanently -
    the next restart will recreate it with a fresh random password, acting
    as a recovery account.
    """
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.username == ROOT_ADMIN_USERNAME))
        if result.scalar_one_or_none() is not None:
            return

        password = secrets.token_urlsafe(12)
        user = User(
            username=ROOT_ADMIN_USERNAME,
            hashed_password=hash_password(password),
            is_admin=True,
            must_change_password=True,
        )
        session.add(user)
        await session.commit()

    print("=" * 50, flush=True)
    print("  ADMIN USER CREATED", flush=True)
    print(f"  Username: {ROOT_ADMIN_USERNAME}", flush=True)
    print(f"  Password: {password}", flush=True)
    print("  Change the password after first login!", flush=True)
    print("=" * 50, flush=True)
