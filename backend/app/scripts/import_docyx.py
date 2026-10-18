"""Импорт каталога из github.com/docyx/pc-part-dataset.

Внутри контейнера api:
  python -m app.scripts.import_docyx --dry-run
  python -m app.scripts.import_docyx --usd-rub-rate 95
  python -m app.scripts.import_docyx --path /tmp/docyx --categories cpu,gpu
Курс задаётся переменной DOCYX_USD_RUB_RATE в .env. Без курса импорт остановится,
--keep-usd оставит цены в долларах. Позиции без цены импортируются (в API «нет данных»),
--skip-unpriced их пропустит. После полного импорта демо-детали seed скрываются, --keep-seed их оставит.
"""
import argparse
import asyncio
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.importers.docyx import FILES, ImportBusyError, import_catalog, load_dataset


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Импорт каталога docyx/pc-part-dataset")
    p.add_argument("--path", type=Path, help="локальная копия репозитория или папка data/json")
    p.add_argument("--ref", default=os.environ.get("DOCYX_REF", "main"), help="ветка или коммит на GitHub")
    p.add_argument("--categories", default=",".join(FILES), help="через запятую: " + ",".join(FILES))
    p.add_argument("--usd-rub-rate", default=os.environ.get("DOCYX_USD_RUB_RATE") or None)
    p.add_argument("--skip-unpriced", action="store_true", help="не импортировать позиции без цены")
    p.add_argument("--keep-usd", action="store_true", help="разрешить импорт без курса, цены в USD")
    p.add_argument("--keep-missing", action="store_true", help="не деактивировать исчезнувшие позиции")
    p.add_argument("--keep-seed", action="store_true", help="не скрывать демо-детали из seed")
    p.add_argument("--dry-run", action="store_true", help="посчитать и откатить транзакцию")
    args = p.parse_args(argv)
    if args.usd_rub_rate is not None:
        try:
            args.usd_rub_rate = Decimal(str(args.usd_rub_rate).replace(",", "."))
        except InvalidOperation:
            p.error("--usd-rub-rate: ожидалось число")
        if args.usd_rub_rate <= 0:
            p.error("--usd-rub-rate должен быть больше нуля")
    elif not args.keep_usd:
        p.error("не задан курс: DOCYX_USD_RUB_RATE в .env или --usd-rub-rate. Для цен в USD добавьте --keep-usd")
    return args


def _retire_seed(args: argparse.Namespace, cats: list[str]) -> bool:
    """Демо-детали скрываем только после полного импорта, иначе каталог останется с дырами."""
    return not args.keep_seed and set(cats) >= set(FILES)


async def _main(args: argparse.Namespace) -> int:
    from app.database import SessionLocal, engine

    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    data = await asyncio.to_thread(load_dataset, args.path, ref=args.ref, categories=cats)
    try:
        async with SessionLocal() as session:
            try:
                stats = await import_catalog(session, data, usd_rate=args.usd_rub_rate,
                                             include_unpriced=not args.skip_unpriced,
                                             retire_missing=not args.keep_missing, retire_seed=_retire_seed(args, cats))
            except ImportBusyError as exc:
                print(json.dumps({"error": "import_busy", "message": str(exc)}, ensure_ascii=False))
                return 3
            if args.dry_run:
                await session.rollback()
            else:
                await session.commit()
    finally:
        await engine.dispose()
    stats["dry_run"] = args.dry_run
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(parse_args())))
