"""Создание администратора или смена пароля.

    docker compose exec api python -m app.scripts.create_admin --username admin
    docker compose exec api python -m app.scripts.create_admin --username admin --reset-password

Пароль запрашивается без отображения. Для автоматизации можно передать ADMIN_PASSWORD.
"""
import argparse
import asyncio
import getpass
import os
import re
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Admin
from app.security import hash_password

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,64}$")
MIN_PASSWORD_LENGTH = 12


def validate(username: str, password: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("Логин: 3-64 символа, строчные латинские буквы, цифры, точка, дефис, подчёркивание")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


async def upsert_admin(session: AsyncSession, username: str, password: str, reset: bool = False) -> str:
    validate(username, password)
    admin = await session.scalar(select(Admin).where(Admin.username == username))
    if admin is None:
        session.add(Admin(username=username, password_hash=hash_password(password)))
        result = "created"
    elif not reset:
        raise ValueError(f"Администратор {username} уже существует. Для смены пароля добавьте --reset-password")
    else:
        admin.password_hash = hash_password(password)
        admin.failed_login_count = 0
        admin.locked_until = None
        admin.is_active = True
        result = "updated"
    await session.commit()
    return result


def _read_password() -> str:
    env_password = os.environ.get("ADMIN_PASSWORD")
    if env_password:
        return env_password
    first = getpass.getpass("Пароль: ")
    if first != getpass.getpass("Повторите пароль: "):
        raise ValueError("Пароли не совпадают")
    return first


async def _main(username: str, reset: bool) -> int:
    from app.database import SessionLocal, engine

    try:
        password = _read_password()
        async with SessionLocal() as session:
            result = await upsert_admin(session, username, password, reset)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print("Администратор создан" if result == "created" else "Пароль обновлён")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Создать администратора")
    parser.add_argument("--username", required=True)
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.username.strip().lower(), args.reset_password)))
