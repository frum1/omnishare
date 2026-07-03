"""Создаёт первого администратора. Запуск: python -m scripts.create_admin"""
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import async_session_maker, init_db
from app.models import User
from app.security import hash_password


async def main() -> None:
    await init_db()

    username = input("Username: ").strip()
    if not username:
        print("Username не может быть пустым")
        return

    password = getpass.getpass("Password: ")
    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        print("Пароли не совпадают")
        return
    if not password:
        print("Пароль не может быть пустым")
        return

    async with async_session_maker() as session:
        existing = await session.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            print(f"Пользователь '{username}' уже существует")
            return

        user = User(username=username, hashed_password=hash_password(password), is_admin=True)
        session.add(user)
        await session.commit()
        print(f"Администратор '{username}' создан")


if __name__ == "__main__":
    asyncio.run(main())
