"""Идемпотентная загрузка стартовых данных.

    docker compose exec api python -m app.scripts.seed

Категории обновляются, правила только добавляются (правки админа сохраняются),
демо-детали обновляются по (source, external_id), смена цены пишется в историю.
"""
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, CompatibilityRule, Manufacturer, Part, PartPriceHistory
from app.seed_data import CATEGORIES, MANUFACTURERS, PARTS, RULES, SEED_SOURCE

CURRENCY = "RUB"


async def seed(session: AsyncSession) -> dict[str, int]:
    stats = {"rules_added": 0, "parts_added": 0, "parts_updated": 0, "prices_recorded": 0}

    for row in CATEGORIES:
        stmt = pg_insert(Category).values(**row)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Category.slug],
                set_={k: stmt.excluded[k] for k in ("name", "sort_order", "is_required", "max_items")},
            )
        )

    await session.execute(
        pg_insert(Manufacturer).values(MANUFACTURERS).on_conflict_do_nothing(index_elements=[Manufacturer.slug])
    )

    for row in RULES:
        added = await session.scalar(
            pg_insert(CompatibilityRule)
            .values(**row)
            .on_conflict_do_nothing(index_elements=[CompatibilityRule.code])
            .returning(CompatibilityRule.id)
        )
        stats["rules_added"] += added is not None

    category_ids = dict((await session.execute(select(Category.slug, Category.id))).all())
    manufacturer_ids = dict((await session.execute(select(Manufacturer.slug, Manufacturer.id))).all())
    existing = {
        p.external_id: p
        for p in await session.scalars(select(Part).where(Part.source == SEED_SOURCE))
    }
    now = datetime.now(UTC)

    for item in PARTS:
        values = {
            "category_id": category_ids[item["category"]],
            "manufacturer_id": manufacturer_ids[item["manufacturer"]],
            "name": item["name"],
            "power_w": item["power_w"],
            "specs": item["specs"],
        }
        part = existing.get(item["key"])
        if part is None:
            part = Part(source=SEED_SOURCE, external_id=item["key"], currency=CURRENCY,
                        price=item["price"], price_updated_at=now, **values)
            session.add(part)
            await session.flush()
            stats["parts_added"] += 1
            price_changed = True
        else:
            changed = False
            for field, value in values.items():
                if getattr(part, field) != value:
                    setattr(part, field, value)
                    changed = True
            price_changed = part.price != item["price"]
            if price_changed:
                part.price = item["price"]
                part.price_updated_at = now
            stats["parts_updated"] += changed or price_changed

        if price_changed:
            session.add(PartPriceHistory(part_id=part.id, price=item["price"], currency=CURRENCY,
                                         source=SEED_SOURCE))
            stats["prices_recorded"] += 1

    await session.commit()
    return stats


async def _main() -> None:
    from app.database import SessionLocal, engine

    try:
        async with SessionLocal() as session:
            stats = await seed(session)
    finally:
        await engine.dispose()
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_main())
