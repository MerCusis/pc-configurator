import os

# Значения по умолчанию для локального запуска без .env.
# В контейнере реальные переменные уже заданы и не перезаписываются.
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef0123456789")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")


# ---------- Интеграционные фикстуры PostgreSQL (этап 2) ----------
import asyncio
import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
_SAFE_DB_NAME = re.compile(r"^[A-Za-z0-9_]+_test$")


def _test_url():
    """Отдельная БД <имя>_test. Рабочая база тестами не затрагивается."""
    from sqlalchemy.engine import make_url

    from app.config import get_settings

    explicit = os.environ.get("TEST_DATABASE_URL")
    url = make_url(explicit) if explicit else make_url(get_settings().database_url)
    if not explicit:
        url = url.set(database=f"{url.database}_test")
    if not _SAFE_DB_NAME.fullmatch(url.database or ""):
        raise RuntimeError(f"Имя тестовой БД должно оканчиваться на _test: {url.database}")
    return url


async def _admin_exec(url, *statements: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(
        user=url.username, password=url.password, host=url.host,
        port=url.port or 5432, database="postgres", timeout=5,
    )
    try:
        for sql in statements:
            await conn.execute(sql)
    finally:
        await conn.close()


def make_alembic_config(url: str):
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def db_url():
    from alembic import command

    url = _test_url()
    name = url.database
    try:
        asyncio.run(_admin_exec(url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(f"PostgreSQL недоступен: {exc}")
        pytest.skip(f"PostgreSQL недоступен, интеграционные тесты пропущены: {exc}")
    rendered = url.render_as_string(hide_password=False)
    command.upgrade(make_alembic_config(rendered), "head")
    yield rendered
    asyncio.run(_admin_exec(url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


class DB:
    """Запуск async-кода с отдельной сессией в синхронном тесте."""

    def __init__(self, url: str):
        self.url = url

    def run(self, fn):
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import NullPool

        async def _go():
            engine = create_async_engine(self.url, poolclass=NullPool)
            try:
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    return await fn(session)
            finally:
                await engine.dispose()

        return asyncio.run(_go())


@pytest.fixture
def db(db_url) -> DB:
    """Чистая БД перед каждым тестом: TRUNCATE всех таблиц приложения."""
    from sqlalchemy import text

    from app.models import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    database = DB(db_url)

    async def _truncate(session):
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()

    database.run(_truncate)
    return database
