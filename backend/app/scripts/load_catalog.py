"""Загрузка стартового каталога из backend/data/catalog_starter.json.

    docker compose exec api python -m app.scripts.load_catalog --dry-run
    docker compose exec api python -m app.scripts.load_catalog --retire-seed

Детали обновляются по (source="starter", key), смена цены пишется в историю.
Повторный запуск ничего не дублирует. Позиции, которых нет в файле, снимаются с продажи.
--retire-seed снимает с продажи 33 демо-детали seed, чтобы в каталоге не было дублей.
"""
import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.catalog_specs import POWER_REQUIRED_CATEGORIES, REQUIRED_SPEC_KEYS
from app.models import Category, Manufacturer, Part, PartPriceHistory

SOURCE = "starter"
FORMAT = "pc-configurator-catalog"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog_starter.json"
MAX_PRICE = Decimal("9999999999.99")


def validate(doc: Any) -> list[str]:
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return [f"Ожидался JSON с format={FORMAT}"]
    makers = doc.get("manufacturers") or {}
    errors: list[str] = []
    seen: set[str] = set()
    for i, p in enumerate(doc.get("parts") or []):
        where = f"parts[{i}] {p.get('key')}"
        cat = p.get("category")
        if cat not in REQUIRED_SPEC_KEYS:
            errors.append(f"{where}: неизвестная категория {cat}")
            continue
        specs = p.get("specs")
        if not isinstance(specs, dict):
            errors.append(f"{where}: specs должен быть объектом")
            continue
        missing = set(REQUIRED_SPEC_KEYS[cat]) - specs.keys()
        if missing:
            errors.append(f"{where}: нет характеристик {sorted(missing)}")
        if cat in POWER_REQUIRED_CATEGORIES and not p.get("power_w"):
            errors.append(f"{where}: для {cat} нужен power_w")
        if p.get("manufacturer") not in makers:
            errors.append(f"{where}: производителя {p.get('manufacturer')} нет в manufacturers")
        if not str(p.get("name") or "").strip():
            errors.append(f"{where}: пустое название")
        if p.get("key") in seen:
            errors.append(f"{where}: повтор key")
        seen.add(p.get("key"))
        try:
            price = Decimal(str(p.get("price")))
            if not (0 <= price <= MAX_PRICE):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            errors.append(f"{where}: некорректная цена {p.get('price')!r}")
    if not seen:
        errors.append("В файле нет деталей")
    return errors


async def load(session, doc: dict[str, Any], *, retire_seed: bool = False) -> dict[str, int]:
    stats = {"added": 0, "updated": 0, "prices_recorded": 0, "retired": 0, "seed_retired": 0}
    cat_ids = dict((await session.execute(select(Category.slug, Category.id))).all())
    absent = {p["category"] for p in doc["parts"]} - cat_ids.keys()
    if absent:
        raise ValueError(f"Категорий {sorted(absent)} нет в БД. Сначала выполните seed")
    makers = doc["manufacturers"]
    await session.execute(pg_insert(Manufacturer).values([{"slug": s, "name": n} for s, n in makers.items()])
                          .on_conflict_do_nothing(index_elements=["slug"]))
    maker_ids = dict((await session.execute(select(Manufacturer.slug, Manufacturer.id))).all())
    existing = {p.external_id: p for p in await session.scalars(select(Part).where(Part.source == SOURCE))}
    currency = doc.get("currency") or "RUB"
    now = datetime.now(UTC)
    for item in doc["parts"]:
        price = Decimal(str(item["price"]))
        values = {"category_id": cat_ids[item["category"]], "manufacturer_id": maker_ids[item["manufacturer"]],
                  "name": item["name"].strip(), "power_w": item.get("power_w"), "specs": item["specs"]}
        part = existing.get(item["key"])
        if part is None:
            part = Part(source=SOURCE, external_id=item["key"], currency=currency, price=price,
                        price_updated_at=now, **values)
            session.add(part)
            await session.flush()
            stats["added"] += 1
            price_changed = True
        else:
            changed = False
            for field, value in values.items():
                if getattr(part, field) != value:
                    setattr(part, field, value)
                    changed = True
            if not part.is_active or part.deleted_at is not None:
                part.is_active, part.deleted_at, changed = True, None, True
            price_changed = part.price != price
            if price_changed:
                part.price, part.price_updated_at = price, now
            stats["updated"] += changed or price_changed
        if price_changed:
            session.add(PartPriceHistory(part_id=part.id, price=price, currency=currency, source=SOURCE))
            stats["prices_recorded"] += 1
    keys = [p["key"] for p in doc["parts"]]
    res = await session.execute(update(Part).where(Part.source == SOURCE, Part.is_active.is_(True),
                                                   Part.external_id.not_in(keys)).values(is_active=False))
    stats["retired"] = res.rowcount or 0
    if retire_seed:
        res = await session.execute(update(Part).where(Part.source == "seed", Part.is_active.is_(True))
                                    .values(is_active=False))
        stats["seed_retired"] = res.rowcount or 0
    return stats


async def _main(args: argparse.Namespace) -> int:
    from app.database import SessionLocal, engine

    try:
        doc = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Не удалось прочитать {args.path}: {exc}", file=sys.stderr)
        return 1
    errors = validate(doc)
    if errors:
        print("Файл не загружен:\n" + "\n".join(errors[:50]), file=sys.stderr)
        return 1
    try:
        async with SessionLocal() as session:
            try:
                stats = await load(session, doc, retire_seed=args.retire_seed)
            except ValueError as exc:
                print(f"Ошибка: {exc}", file=sys.stderr)
                return 1
            await (session.rollback() if args.dry_run else session.commit())
    finally:
        await engine.dispose()
    print(json.dumps({**stats, "parts_in_file": len(doc["parts"]), "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Загрузка стартового каталога")
    ap.add_argument("--path", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--retire-seed", action="store_true", help="снять с продажи демо-детали seed")
    ap.add_argument("--dry-run", action="store_true", help="проверить и откатить транзакцию")
    sys.exit(asyncio.run(_main(ap.parse_args())))
