"""Каталог: категории, производители, поиск и фильтры деталей."""
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_error
from app.api.presenters import present_part
from app.database import get_db
from app.models.catalog import Category, Manufacturer, Part

router = APIRouter(tags=["catalog"])


def _available():
    return and_(Part.is_active.is_(True), Part.deleted_at.is_(None))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _base_query():
    return (
        select(Part, Category.slug, Manufacturer.name)
        .join(Category, Part.category_id == Category.id)
        .outerjoin(Manufacturer, Part.manufacturer_id == Manufacturer.id)
        .where(_available())
    )


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Category, func.count(Part.id))
        .outerjoin(Part, and_(Part.category_id == Category.id, _available()))
        .group_by(Category.id)
        .order_by(Category.sort_order, Category.id)
    )).all()
    return [
        {"slug": c.slug, "name": c.name, "is_required": c.is_required, "max_items": c.max_items, "part_count": n}
        for c, n in rows
    ]


@router.get("/manufacturers")
async def list_manufacturers(category: str | None = Query(None, max_length=32), db: AsyncSession = Depends(get_db)):
    stmt = (select(Manufacturer.slug, Manufacturer.name, func.count(Part.id))
            .join(Part, Part.manufacturer_id == Manufacturer.id)
            .join(Category, Part.category_id == Category.id)
            .where(_available()))
    if category:
        stmt = stmt.where(Category.slug == category)
    rows = (await db.execute(stmt.group_by(Manufacturer.id).order_by(Manufacturer.name))).all()
    return [{"slug": s, "name": n, "part_count": c} for s, n, c in rows]


@router.get("/parts")
async def list_parts(
    category: str | None = Query(None, max_length=32),
    q: str | None = Query(None, max_length=100, description="поиск по названию"),
    manufacturer: str | None = Query(None, max_length=64, description="slug производителя"),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    has_price: bool | None = Query(None, description="false — только позиции без цены"),
    socket: str | None = Query(None, max_length=32),
    form_factor: str | None = Query(None, max_length=32),
    memory_type: str | None = Query(None, max_length=16),
    sort: Literal["name", "price", "-price"] = "name",
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
    db: AsyncSession = Depends(get_db),
):
    conds = []
    if category:
        conds.append(Category.slug == category)
    if q and q.strip():
        conds.append(Part.name.ilike(f"%{_escape_like(q.strip())}%", escape="\\"))
    if manufacturer:
        conds.append(Manufacturer.slug == manufacturer)
    if min_price is not None:
        conds.append(Part.price >= min_price)
    if max_price is not None:
        conds.append(Part.price <= max_price)
    if has_price is not None:
        conds.append(Part.price.is_not(None) if has_price else Part.price.is_(None))
    # Фильтры по характеристикам: одиночное значение или вхождение в список (кулеры, корпуса, CPU)
    if socket:
        conds.append(or_(Part.specs.contains({"socket": socket}), Part.specs.contains({"sockets": [socket]})))
    if form_factor:
        conds.append(or_(Part.specs.contains({"form_factor": form_factor}),
                         Part.specs.contains({"motherboard_form_factors": [form_factor]})))
    if memory_type:
        conds.append(or_(Part.specs.contains({"memory_type": memory_type}),
                         Part.specs.contains({"memory_types": [memory_type]})))
    stmt = _base_query().where(*conds)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {
        "name": (Part.name.asc(), Part.id.asc()),
        "price": (Part.price.asc().nulls_last(), Part.id.asc()),
        "-price": (Part.price.desc().nulls_last(), Part.id.asc()),
    }[sort]
    rows = (await db.execute(stmt.order_by(*order).limit(limit).offset(offset))).all()
    return {"items": [present_part(p, slug, m) for p, slug, m in rows], "total": total,
            "limit": limit, "offset": offset}


@router.get("/parts/{part_id}")
async def get_part(part_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(_base_query().where(Part.id == part_id))).first()
    if row is None:
        raise api_error(404, "part_not_found", "Деталь не найдена")
    return present_part(*row)
