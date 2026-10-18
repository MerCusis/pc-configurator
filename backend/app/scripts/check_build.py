"""Проверка сборки из демо-деталей seed по их ключам.

    docker compose exec api python -m app.scripts.check_build amd-ryzen5-7600 msi-b650-gaming-plus-wifi kingston-fury-ddr5-32-6000:2

Ключ с суффиксом :N задаёт количество. Вывод — одна строка JSON.
"""
import argparse
import asyncio
import json
import sys

from sqlalchemy import select

from app.models import Part
from app.seed_data import SEED_SOURCE
from app.services.build_check import UnknownPartsError, check_items


def _parse(arg: str) -> tuple[str, int]:
    key, _, qty = arg.partition(":")
    return key, int(qty) if qty else 1


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Проверка совместимости демо-сборки")
    parser.add_argument("parts", nargs="+", help="ключи деталей из seed, например amd-ryzen5-7600 или kit:2")
    args = parser.parse_args(argv)
    try:
        items = [_parse(a) for a in args.parts]
    except ValueError:
        parser.error("количество после двоеточия должно быть целым числом")

    from app.database import SessionLocal, engine

    try:
        async with SessionLocal() as session:
            keys = [k for k, _ in items]
            ids = dict((await session.execute(
                select(Part.external_id, Part.id).where(Part.source == SEED_SOURCE, Part.external_id.in_(keys))
            )).all())
            unknown = [k for k in keys if k not in ids]
            if unknown:
                print(json.dumps({"error": "unknown_parts", "keys": unknown}, ensure_ascii=False))
                return 2
            try:
                result = await check_items(session, [(ids[k], q) for k, q in items])
            except (UnknownPartsError, ValueError) as exc:
                print(json.dumps({"error": "invalid_items", "message": str(exc)}, ensure_ascii=False))
                return 2
    finally:
        await engine.dispose()
    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
