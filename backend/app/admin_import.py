"""Импорт каталога из JSON-файла через админку."""
import json
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqladmin import BaseView, expose
from sqlalchemy import func, select, update
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.database import SessionLocal
from app.models import AuditLog, Category, Manufacturer, Part, PartPriceHistory

logger = logging.getLogger(__name__)

UPLOAD_SOURCE = "upload"
PRICE_SOURCE = "import"
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_ROWS = 200_000
MAX_ERRORS_SHOWN = 30
MAX_PRICE = Decimal("9999999999.99")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
FIELDS = ("category_id", "manufacturer_id", "name", "price", "currency", "power_w", "specs", "is_active")


def _parse(raw: Any, i: int, categories: dict[str, int], errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        errors.append(f"Запись {i}: ожидался объект")
        return None
    start = len(errors)
    ext = str(raw.get("external_id") or "").strip()
    where = f"Запись {i} ({ext})" if ext else f"Запись {i}"
    if not ext or len(ext) > 100:
        errors.append(f"{where}: external_id обязателен, до 100 символов")

    name = str(raw.get("name") or "").strip()
    if not name or len(name) > 255:
        errors.append(f"{where}: name обязателен, до 255 символов")

    category_id = categories.get(str(raw.get("category") or "").strip().lower())
    if category_id is None:
        errors.append(f"{where}: неизвестная категория {raw.get('category')!r}")

    man = raw.get("manufacturer")
    man = str(man).strip() or None if man is not None else None
    if man and len(man) > 100:
        errors.append(f"{where}: manufacturer до 100 символов")

    price = raw.get("price")
    if price in (None, ""):
        price = None
    else:
        try:
            if isinstance(price, bool):
                raise InvalidOperation
            price = Decimal(str(price)).quantize(Decimal("0.01"))
            ok = 0 <= price <= MAX_PRICE
        except (InvalidOperation, ValueError):
            ok = False
        if not ok:
            errors.append(f"{where}: цена должна быть числом от 0 до 9999999999.99")

    currency = str(raw.get("currency") or "RUB").strip().upper()
    if not CURRENCY_RE.fullmatch(currency):
        errors.append(f"{where}: валюта из трёх латинских букв, например RUB")

    power = raw.get("power_w")
    if power in (None, ""):
        power = None
    elif isinstance(power, bool) or not isinstance(power, int) or not 0 <= power <= 32767:
        errors.append(f"{where}: power_w целое от 0 до 32767")

    specs = raw.get("specs") or {}
    if not isinstance(specs, dict):
        errors.append(f"{where}: specs должен быть объектом {{...}}")

    is_active = raw.get("is_active", True)
    if not isinstance(is_active, bool):
        errors.append(f"{where}: is_active должен быть true или false")

    if len(errors) > start:
        return None
    return {"external_id": ext, "manufacturer": man, "category_id": category_id, "name": name,
            "price": price, "currency": currency, "power_w": power, "specs": specs, "is_active": is_active}


async def run_import(rows: list[Any], *, deactivate_missing: bool, dry_run: bool,
                     admin_id: int | None, ip: str | None, filename: str) -> tuple[dict[str, int], list[str]]:
    errors: list[str] = []
    async with SessionLocal() as s:
        categories = {c.name.strip().lower(): c.id for c in await s.scalars(select(Category))}
        parsed: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, raw in enumerate(rows, 1):
            item = _parse(raw, i, categories, errors)
            if item is None:
                continue
            if item["external_id"] in seen:
                errors.append(f"Запись {i}: external_id {item['external_id']!r} повторяется")
                continue
            seen.add(item["external_id"])
            parsed.append(item)
        if errors:
            return {}, errors

        now = datetime.now(UTC)
        stats = {"created": 0, "updated": 0, "unchanged": 0, "deactivated": 0, "manufacturers": 0}

        mans = {m.name.strip().lower(): m for m in await s.scalars(select(Manufacturer))}
        for item in parsed:
            n = item["manufacturer"]
            if n and n.lower() not in mans:
                mans[n.lower()] = Manufacturer(name=n)
                s.add(mans[n.lower()])
                stats["manufacturers"] += 1
        await s.flush()

        existing = {p.external_id: p for p in await s.scalars(select(Part).where(Part.source == UPLOAD_SOURCE))}
        new_parts: list[Part] = []
        for item in parsed:
            ext = item.pop("external_id")
            n = item.pop("manufacturer")
            item["manufacturer_id"] = mans[n.lower()].id if n else None
            part = existing.pop(ext, None)
            if part is None:
                part = Part(source=UPLOAD_SOURCE, external_id=ext, updated_at=now,
                            price_updated_at=now if item["price"] is not None else None, **item)
                s.add(part)
                new_parts.append(part)
                stats["created"] += 1
                continue
            changed = [k for k in FIELDS if getattr(part, k) != item[k]]
            if part.deleted_at is not None:
                part.deleted_at = None
                changed.append("deleted_at")
            if not changed:
                stats["unchanged"] += 1
                continue
            if "price" in changed:
                part.price_updated_at = now if item["price"] is not None else None
                if item["price"] is not None:
                    s.add(PartPriceHistory(part_id=part.id, price=item["price"],
                                           currency=item["currency"], source=PRICE_SOURCE))
            for k in FIELDS:
                setattr(part, k, item[k])
            part.updated_at = now
            stats["updated"] += 1

        if deactivate_missing:
            # В existing остались детали прошлых загрузок, которых нет в новом файле
            for part in existing.values():
                if part.is_active:
                    part.is_active = False
                    part.updated_at = now
                    stats["deactivated"] += 1
            res = await s.execute(
                update(Part).where(Part.source != UPLOAD_SOURCE, Part.is_active.is_(True))
                .values(is_active=False, updated_at=func.now())
            )
            stats["deactivated"] += res.rowcount or 0

        await s.flush()
        for part in new_parts:
            if part.price is not None:
                s.add(PartPriceHistory(part_id=part.id, price=part.price,
                                       currency=part.currency, source=PRICE_SOURCE))
        s.add(AuditLog(admin_id=admin_id, action="catalog.import", entity_type="part", entity_id=None,
                       details={**stats, "file": filename[:200], "deactivate_missing": deactivate_missing},
                       ip_address=ip))
        if dry_run:
            await s.rollback()
        else:
            await s.commit()
    return stats, []


async def _read_rows(upload: Any) -> tuple[list[Any], str | None]:
    if not isinstance(upload, UploadFile) or not upload.filename:
        return [], "Выберите файл"
    data = await upload.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        return [], "Файл больше 50 МБ"
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except ValueError as e:
        return [], f"Файл не читается как JSON в UTF-8: {e}"
    rows = doc.get("parts") if isinstance(doc, dict) else doc
    if not isinstance(rows, list) or not rows:
        return [], 'Ожидался непустой список деталей или объект {"parts": [...]}'
    if len(rows) > MAX_ROWS:
        return [], f"В файле больше {MAX_ROWS} записей"
    return rows, None


class ImportView(BaseView):
    name = "Импорт базы"
    icon = "fa-solid fa-file-import"
    auth: Any = None  # задаётся в setup_admin

    @expose("/import", methods=["GET", "POST"])
    async def import_page(self, request: Request) -> Response:
        if self.auth is None or not await self.auth.authenticate(request):
            return RedirectResponse(request.url_for("admin:login"), status_code=302)
        ctx: dict[str, Any] = {"stats": None, "errors": [], "errors_total": 0, "dry_run": False}
        if request.method == "POST":
            form = await request.form(max_files=1, max_fields=5)
            try:
                upload = form.get("file")
                ctx["dry_run"] = form.get("dry_run") is not None
                rows, err = await _read_rows(upload)
                if err:
                    errors: list[str] = [err]
                    stats = None
                else:
                    try:
                        stats, errors = await run_import(
                            rows, deactivate_missing=form.get("deactivate_missing") is not None,
                            dry_run=ctx["dry_run"], admin_id=getattr(request.state, "admin_id", None),
                            ip=request.client.host if request.client else None,
                            filename=upload.filename or "",
                        )
                    except Exception:
                        logger.exception("Импорт каталога упал")
                        stats, errors = None, ["Ошибка базы данных, подробности в docker compose logs api"]
                ctx["stats"] = stats or None
                ctx["errors"] = errors[:MAX_ERRORS_SHOWN]
                ctx["errors_total"] = len(errors)
            finally:
                await form.close()
        return await self.templates.TemplateResponse(request, "import.html", ctx)