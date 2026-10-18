"""Состояние БД одной JSON-строкой: ревизия миграций и количество записей.

    docker compose exec api python -m app.scripts.db_status
"""
import asyncio
import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from app.models import Admin, AnonSession, Build, Category, CompatibilityRule, Manufacturer, Part, PartPriceHistory

BACKEND_DIR = Path(__file__).resolve().parents[2]
MODELS = {
    "categories": Category, "manufacturers": Manufacturer, "parts": Part,
    "price_history": PartPriceHistory, "rules": CompatibilityRule,
    "admins": Admin, "sessions": AnonSession, "builds": Build,
}


def head_revision() -> str | None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


async def _main() -> None:
    from app.database import SessionLocal, engine

    try:
        async with SessionLocal() as s:
            revision = await s.scalar(text("SELECT version_num FROM alembic_version"))
            counts = {name: await s.scalar(select(func.count()).select_from(m)) for name, m in MODELS.items()}
    finally:
        await engine.dispose()
    head = head_revision()
    print(json.dumps({"revision": revision, "head": head, "up_to_date": revision == head, **counts}))


if __name__ == "__main__":
    asyncio.run(_main())
