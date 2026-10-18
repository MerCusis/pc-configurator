"""Связка движка совместимости с БД: правила, категории и детали из PostgreSQL."""
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, CompatibilityRule, Part
from app.services.compatibility import CheckResult, RuleConfig, check_build
from app.services.parts import BuildPart

MAX_QUANTITY = 16  # совпадает с build_items.quantity_range
MAX_DISTINCT_PARTS = 64


class UnknownPartsError(LookupError):
    """Деталь не найдена, удалена или снята с продажи."""

    def __init__(self, part_ids: Iterable[int]):
        self.part_ids = tuple(sorted(part_ids))
        super().__init__(f"Детали недоступны: {list(self.part_ids)}")


def normalize_items(items: Iterable[tuple[int, int]]) -> dict[int, int]:
    """Склеивает повторы part_id и проверяет количество. Порядок первого появления сохраняется."""
    result: dict[int, int] = {}
    for part_id, qty in items:
        if isinstance(part_id, bool) or not isinstance(part_id, int) or part_id <= 0:
            raise ValueError(f"Некорректный part_id: {part_id!r}")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ValueError(f"Некорректное количество для {part_id}: {qty!r}")
        result[part_id] = result.get(part_id, 0) + qty
        if result[part_id] > MAX_QUANTITY:
            raise ValueError(f"Количество для {part_id} больше {MAX_QUANTITY}")
    if len(result) > MAX_DISTINCT_PARTS:
        raise ValueError(f"В сборке больше {MAX_DISTINCT_PARTS} разных деталей")
    return result


async def load_rule_configs(session: AsyncSession) -> dict[str, RuleConfig]:
    rows = await session.scalars(select(CompatibilityRule))
    return {r.code: RuleConfig(r.code, r.severity, r.is_enabled, dict(r.params or {})) for r in rows}


async def load_categories(session: AsyncSession) -> tuple[dict[str, int], tuple[str, ...]]:
    rows = (await session.execute(
        select(Category.slug, Category.max_items, Category.is_required).order_by(Category.sort_order)
    )).all()
    return {slug: limit for slug, limit, _ in rows}, tuple(slug for slug, _, req in rows if req)


async def load_build_parts(session: AsyncSession, items: dict[int, int]) -> list[BuildPart]:
    if not items:
        return []
    rows = (await session.execute(
        select(Part, Category.slug)
        .join(Category, Part.category_id == Category.id)
        .where(Part.id.in_(items), Part.deleted_at.is_(None), Part.is_active)
    )).all()
    found = {part.id: (part, slug) for part, slug in rows}
    missing = set(items) - set(found)
    if missing:
        raise UnknownPartsError(missing)
    return [
        BuildPart(part_id=pid, category=found[pid][1], name=found[pid][0].name,
                  specs=found[pid][0].specs or {}, power_w=found[pid][0].power_w,
                  quantity=qty, price=found[pid][0].price)
        for pid, qty in items.items()
    ]


async def check_items(session: AsyncSession, items: Iterable[tuple[int, int]]) -> CheckResult:
    """Проверка набора (part_id, quantity) по правилам и категориям из БД."""
    normalized = normalize_items(items)
    parts = await load_build_parts(session, normalized)
    rules = await load_rule_configs(session)
    limits, required = await load_categories(session)
    return check_build(parts, rules, category_limits=limits, required_categories=required)
