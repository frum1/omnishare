"""Resets a user's password directly via the DB, for when you're locked out
and have no other admin account to do it through the API.

Run: python -m scripts.reset_admin_password [username]
(defaults to the root admin account "admin")
"""
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import User
from app.db.session import async_session_maker, init_db
from app.services.bootstrap import ROOT_ADMIN_USERNAME


async def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else ROOT_ADMIN_USERNAME

    await init_db()

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None:
            print(f"User '{username}' not found.")
            if username == ROOT_ADMIN_USERNAME:
                print("Restart the service instead - it will recreate the admin account.")
            return

        password = secrets.token_urlsafe(12)
        user.hashed_password = hash_password(password)
        user.must_change_password = True
        await session.commit()

    print("=" * 50)
    print("  PASSWORD RESET")
    print(f"  Username: {username}")
    print(f"  Password: {password}")
    print("  Change the password after logging in!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
