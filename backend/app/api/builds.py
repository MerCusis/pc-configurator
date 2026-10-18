"""Сборки гостя, публичные ссылки и проверка совместимости."""
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_error, current_session
from app.api.presenters import is_estimate, present_part, present_totals
from app.api.sessions import MAX_BUILDS_PER_SESSION
from app.database import get_db
from app.models.build import Build, BuildItem
from app.models.catalog import Category, Manufacturer, Part
from app.models.session import AnonSession
from app.services.build_check import UnknownPartsError, check_items, normalize_items

router = APIRouter(tags=["builds"])
SLUG_PATTERN = r"^[A-Za-z0-9_-]{8,16}$"


class ItemIn(BaseModel):
    part_id: int = Field(gt=0, lt=2**63)
    quantity: int = Field(default=1, ge=1, le=16)


class ItemsIn(BaseModel):
    items: list[ItemIn] = Field(default_factory=list, max_length=64)

    def pairs(self) -> list[tuple[int, int]]:
        return [(i.part_id, i.quantity) for i in self.items]


class BuildIn(ItemsIn):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("description")
    @classmethod
    def _description(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


async def _check(db: AsyncSession, pairs: list[tuple[int, int]]):
    try:
        return await check_items(db, pairs)
    except UnknownPartsError as exc:
        raise api_error(422, "unknown_parts", str(exc), part_ids=list(exc.part_ids)) from exc
    except ValueError as exc:
        raise api_error(422, "invalid_items", str(exc)) from exc


async def _estimate(db: AsyncSession, part_ids: list[int]) -> bool:
    if not part_ids:
        return False
    rows = (await db.execute(select(Part.source, Part.price).where(Part.id.in_(part_ids)))).all()
    return any(is_estimate(s, p) for s, p in rows)


async def _check_payload(db: AsyncSession, pairs: list[tuple[int, int]]) -> tuple[Any, dict[str, Any]]:
    result = await _check(db, pairs)
    ids = list({pid for pid, _ in pairs})
    totals = present_totals(result.total_price, item_count=len(ids),
                            unpriced_count=len(result.unpriced_part_ids), estimate=await _estimate(db, ids))
    return result, {**result.to_dict(), **totals}


@router.post("/compatibility/check")
async def check_compatibility(data: ItemsIn, db: AsyncSession = Depends(get_db)):
    """Проверка без сохранения. Токен не нужен."""
    _, payload = await _check_payload(db, data.pairs())
    return payload


async def _build_payload(db: AsyncSession, build: Build, *, owner: bool) -> dict[str, Any]:
    rows = (await db.execute(
        select(BuildItem, Part, Category.slug, Manufacturer.name)
        .join(Part, BuildItem.part_id == Part.id)
        .join(Category, Part.category_id == Category.id)
        .outerjoin(Manufacturer, Part.manufacturer_id == Manufacturer.id)
        .where(BuildItem.build_id == build.id)
        .order_by(Category.sort_order, BuildItem.id)
    )).all()
    items, available, unavailable = [], [], []
    for item, part, slug, maker in rows:
        ok = part.is_active and part.deleted_at is None
        (available if ok else unavailable).append((item.part_id, item.quantity))
        items.append({
            "part": present_part(part, slug, maker),
            "quantity": item.quantity,
            "price_snapshot": None if item.price_snapshot is None else str(item.price_snapshot),
            "is_available": ok,
        })
    # Снятые с продажи детали в проверку не идут, но остаются в составе со статусом is_available=false
    _, check = await _check_payload(db, available)
    payload = {
        "id": str(build.id),
        "name": build.name,
        "description": build.description,
        "is_public": build.is_public,
        "share_slug": build.share_slug if build.is_public else None,
        "share_path": f"/b/{build.share_slug}" if build.is_public else None,
        "created_at": build.created_at.isoformat(),
        "updated_at": build.updated_at.isoformat(),
        "items": items,
        "unavailable_part_ids": [pid for pid, _ in unavailable],
        "check": check,
    }
    payload.update({k: check[k] for k in ("total_price_display", "total_price_is_estimate",
                                          "total_price_note", "unpriced_count")})
    payload["total_price"] = check["total_price"]
    payload["is_owner"] = owner
    return payload


async def _save(db: AsyncSession, build: Build, data: BuildIn) -> None:
    pairs = data.pairs()
    result = await _check(db, pairs)
    if result.errors:
        raise api_error(422, "incompatible_build", "Сборка несовместима, исправьте ошибки перед сохранением",
                        check=result.to_dict())
    items = normalize_items(pairs)
    prices = dict((await db.execute(select(Part.id, Part.price).where(Part.id.in_(list(items))))).all()) \
        if items else {}
    build.name = data.name
    build.description = data.description
    all_unpriced = bool(items) and len(result.unpriced_part_ids) >= len(items)
    build.total_price = None if all_unpriced else result.total_price
    build.total_power_w = result.power.peak_w
    await db.flush()
    await db.execute(delete(BuildItem).where(BuildItem.build_id == build.id))
    db.add_all(BuildItem(build_id=build.id, part_id=pid, quantity=qty, price_snapshot=prices.get(pid))
               for pid, qty in items.items())
    await db.commit()
    await db.refresh(build)


async def _owned(db: AsyncSession, s: AnonSession, build_id: uuid.UUID) -> Build:
    build = await db.scalar(select(Build).where(Build.id == build_id, Build.session_id == s.id))
    if build is None:
        raise api_error(404, "build_not_found", "Сборка не найдена")
    return build


@router.get("/builds")
async def list_builds(s: AnonSession = Depends(current_session), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Build, func.count(BuildItem.id))
        .outerjoin(BuildItem, BuildItem.build_id == Build.id)
        .where(Build.session_id == s.id)
        .group_by(Build.id)
        .order_by(Build.updated_at.desc())
    )).all()
    from app.api.presenters import format_money
    return {
        "items": [{
            "id": str(b.id), "name": b.name, "is_public": b.is_public,
            "share_slug": b.share_slug if b.is_public else None,
            "total_price": None if b.total_price is None else str(b.total_price),
            "total_price_display": format_money(b.total_price) if n else format_money(0),
            "total_power_w": b.total_power_w, "item_count": n, "updated_at": b.updated_at.isoformat(),
        } for b, n in rows],
        "count": len(rows),
        "limit": MAX_BUILDS_PER_SESSION,
    }


@router.post("/builds", status_code=201)
async def create_build(data: BuildIn, s: AnonSession = Depends(current_session),
                       db: AsyncSession = Depends(get_db)):
    # Блокировка строки сессии: два параллельных запроса не обойдут лимит
    await db.execute(select(AnonSession.id).where(AnonSession.id == s.id).with_for_update())
    count = await db.scalar(select(func.count()).select_from(Build).where(Build.session_id == s.id))
    if count >= MAX_BUILDS_PER_SESSION:
        raise api_error(409, "build_limit", f"Можно сохранить не больше {MAX_BUILDS_PER_SESSION} сборок",
                        limit=MAX_BUILDS_PER_SESSION)
    build = Build(session_id=s.id, name=data.name, description=data.description)
    db.add(build)
    await _save(db, build, data)
    return await _build_payload(db, build, owner=True)


@router.get("/builds/{build_id}")
async def get_build(build_id: uuid.UUID, s: AnonSession = Depends(current_session),
                    db: AsyncSession = Depends(get_db)):
    return await _build_payload(db, await _owned(db, s, build_id), owner=True)


@router.put("/builds/{build_id}")
async def update_build(build_id: uuid.UUID, data: BuildIn, s: AnonSession = Depends(current_session),
                       db: AsyncSession = Depends(get_db)):
    build = await _owned(db, s, build_id)
    await _save(db, build, data)
    return await _build_payload(db, build, owner=True)


@router.delete("/builds/{build_id}", status_code=204)
async def delete_build(build_id: uuid.UUID, s: AnonSession = Depends(current_session),
                       db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, s, build_id))
    await db.commit()
    return Response(status_code=204)


@router.post("/builds/{build_id}/share")
async def share_build(build_id: uuid.UUID, s: AnonSession = Depends(current_session),
                      db: AsyncSession = Depends(get_db)):
    build = await _owned(db, s, build_id)
    if not build.share_slug:
        build.share_slug = secrets.token_urlsafe(9)  # 12 символов, ~72 бита
    build.is_public = True
    await db.commit()
    return {"share_slug": build.share_slug, "share_path": f"/b/{build.share_slug}",
            "api_path": f"/api/v1/shared/{build.share_slug}"}


@router.delete("/builds/{build_id}/share", status_code=204)
async def unshare_build(build_id: uuid.UUID, s: AnonSession = Depends(current_session),
                        db: AsyncSession = Depends(get_db)):
    build = await _owned(db, s, build_id)
    # Старая ссылка перестаёт работать; при повторной публикации будет новая
    build.is_public = False
    build.share_slug = None
    await db.commit()
    return Response(status_code=204)


@router.get("/shared/{slug}")
async def get_shared(slug: str = Path(pattern=SLUG_PATTERN), db: AsyncSession = Depends(get_db)):
    build = await db.scalar(select(Build).where(Build.share_slug == slug, Build.is_public.is_(True)))
    if build is None:
        raise api_error(404, "build_not_found", "Сборка не найдена или ссылка отозвана")
    return await _build_payload(db, build, owner=False)
