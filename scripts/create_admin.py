"""Creates the first administrator. Run: python -m scripts.create_admin"""
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import User
from app.db.session import async_session_maker, init_db


async def main() -> None:
    await init_db()

    username = input("Username: ").strip()
    if not username:
        print("Username cannot be empty")
        return

    password = getpass.getpass("Password: ")
    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        print("Passwords do not match")
        return
    if not password:
        print("Password cannot be empty")
        return

    async with async_session_maker() as session:
        existing = await session.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            print(f"User '{username}' already exists")
            return

        user = User(username=username, hashed_password=hash_password(password), is_admin=True)
        session.add(user)
        await session.commit()
        print(f"Administrator '{username}' created")


if __name__ == "__main__":
    asyncio.run(main())
