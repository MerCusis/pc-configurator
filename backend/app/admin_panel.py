"""Админка каталога на SQLAdmin: http://localhost:8080/api/v1/admin

Вход по таблице admins (создаётся скриптом app.scripts.create_admin), пароль Argon2id.
Детали не удаляются, потому что на них ссылаются сохранённые сборки. Вместо удаления их снимают с продажи.
Смена цены пишется в part_price_history, все действия в audit_log.
"""
import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from pathlib import Path

from fastapi import FastAPI
from sqladmin import Admin as SQLAdmin
from sqladmin import ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqladmin.filters import BooleanFilter, ForeignKeyFilter
from sqlalchemy import func, select, update
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.api.presenters import format_money
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import Admin, AuditLog, Category, Part, PartPriceHistory
from app.security import hash_password, verify_password
from app.admin_import import ImportView

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_FAILED_LOGINS = 5
LOCK_TIME = timedelta(minutes=15)
SESSION_MAX_AGE = 8 * 3600  # 8 часов
MAX_PRICE = Decimal("9999999999.99")  # Numeric(12, 2)
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
PRICE_SOURCE = "admin"
TRACKED = ("name", "price", "currency", "power_w", "specs", "is_active")
# Для несуществующего логина пароль тоже проверяется, чтобы по времени ответа нельзя было угадать логин
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _now() -> datetime:
    return datetime.now(UTC)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _fingerprint(password_hash: str) -> str:
    """Попадает в cookie: после смены пароля старые сессии перестают работать."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def _text(v: Any) -> Any:
    return str(v) if isinstance(v, Decimal) else v


def _audit(request: Request, action_name: str, entity_id: Any, details: dict[str, Any]) -> AuditLog:
    return AuditLog(
        admin_id=getattr(request.state, "admin_id", None), action=action_name, entity_type="part",
        entity_id=None if entity_id is None else str(entity_id), details=details, ip_address=_ip(request),
    )


def _secret(value: Any) -> str:
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)


class AdminAuth(AuthenticationBackend):
    def __init__(self, secret_key: str) -> None:
        super().__init__(secret_key)
        # Своя cookie: недоступна из JS, не уходит с чужих сайтов, в production только по HTTPS
        self.middlewares = [Middleware(
            SessionMiddleware, secret_key=secret_key, session_cookie="pcc_admin",
            max_age=SESSION_MAX_AGE, same_site="strict", https_only=settings.is_production,
        )]

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username") or "").strip().lower()
        password = str(form.get("password") or "")
        async with SessionLocal() as s:
            admin = await s.scalar(select(Admin).where(Admin.username == username).with_for_update())
            now = _now()
            if admin is None or not admin.is_active or (admin.locked_until and admin.locked_until > now):
                verify_password(_DUMMY_HASH, password)
                return False
            if not verify_password(admin.password_hash, password):
                admin.failed_login_count += 1
                if admin.failed_login_count >= MAX_FAILED_LOGINS:
                    admin.failed_login_count = 0
                    admin.locked_until = now + LOCK_TIME
                    logger.warning("Admin %s locked after %s failed logins", admin.username, MAX_FAILED_LOGINS)
                await s.commit()
                return False
            admin.failed_login_count = 0
            admin.locked_until = None
            admin.last_login_at = now
            s.add(AuditLog(admin_id=admin.id, action="admin.login", entity_type="admin",
                           entity_id=str(admin.id), details={}, ip_address=_ip(request)))
            await s.commit()
            request.session.clear()
            request.session.update({"admin_id": admin.id, "pw": _fingerprint(admin.password_hash)})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        admin_id = request.session.get("admin_id")
        if not isinstance(admin_id, int):
            return False
        async with SessionLocal() as s:
            admin = await s.get(Admin, admin_id)
        ok = (admin is not None and admin.is_active
              and not (admin.locked_until and admin.locked_until > _now())
              and request.session.get("pw") == _fingerprint(admin.password_hash))
        if not ok:
            request.session.clear()
            return False
        request.state.admin_id = admin.id
        return True


def _selected_ids(request: Request) -> list[int]:
    ids: list[int] = []
    for raw in request.query_params.get("pks", "").split(",")[:1000]:
        if raw.isdigit() and 0 < int(raw) < 2**63:
            ids.append(int(raw))
    return ids


class PartAdmin(ModelView, model=Part):
    name = "Деталь"
    name_plural = "Детали"
    icon = "fa-solid fa-microchip"
    page_size = 50
    page_size_options = [25, 50, 100]
    can_delete = False  # на детали ссылаются сборки, вместо удаления снимаем с продажи

    column_list = [Part.id, Part.category, Part.manufacturer, Part.name, Part.price, Part.power_w,
                   Part.is_active, Part.source, Part.updated_at]
    column_labels = {
        Part.id: "ID", Part.category: "Категория", Part.manufacturer: "Производитель", Part.name: "Название",
        Part.price: "Цена", Part.currency: "Валюта", Part.power_w: "Потребление, Вт", Part.specs: "Характеристики",
        Part.is_active: "В продаже", Part.source: "Источник", Part.external_id: "Внешний ID",
        Part.price_updated_at: "Цена обновлена", Part.deleted_at: "Удалена",
        Part.created_at: "Создана", Part.updated_at: "Изменена",
    }
    column_formatters = {Part.price: lambda m, _: format_money(m.price, m.currency)}
    column_formatters_detail = column_formatters
    column_searchable_list = [Part.name, Part.external_id]
    column_sortable_list = [Part.id, Part.name, Part.price, Part.is_active, Part.updated_at]
    column_default_sort = [(Part.id, True)]
    column_filters = [
        ForeignKeyFilter(Part.category_id, Category.name, foreign_model=Category, title="Категория"),
        BooleanFilter(Part.is_active, title="В продаже"),
    ]
    column_details_exclude_list = [Part.search_vector]  # deferred-колонка, в async её нельзя догрузить
    form_columns = [Part.category, Part.manufacturer, Part.name, Part.price, Part.currency,
                    Part.power_w, Part.specs, Part.is_active]
    form_ajax_refs = {"manufacturer": {"fields": ("name",), "order_by": "name"}}

    async def on_model_change(self, data: dict[str, Any], model: Part, is_created: bool, request: Request) -> None:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Укажите название")
        data["name"] = name
        currency = (data.get("currency") or "RUB").strip().upper()
        if not CURRENCY_RE.fullmatch(currency):
            raise ValueError("Валюта: три латинские буквы, например RUB")
        data["currency"] = currency
        price = data.get("price")
        if price is not None and not (0 <= price <= MAX_PRICE):
            raise ValueError("Цена должна быть от 0 до 9 999 999 999,99")
        power = data.get("power_w")
        if power is not None and not (0 <= power <= 32767):
            raise ValueError("Потребление: от 0 до 32767 Вт")
        specs = data.get("specs")
        if specs in (None, ""):
            data["specs"] = {}
        elif not isinstance(specs, dict):
            raise ValueError('Характеристики должны быть JSON-объектом, например {"socket": "AM5"}')

        # Старые значения читаем из БД отдельно, чтобы не зависеть от порядка вызовов внутри SQLAdmin
        old: dict[str, Any] = {}
        if not is_created:
            async with SessionLocal() as s:
                row = (await s.execute(select(*(getattr(Part, k) for k in TRACKED))
                                       .where(Part.id == model.id))).one()
            old = dict(zip(TRACKED, row))
        price_changed = price is not None if is_created else price != old["price"]
        now = _now()
        if price_changed:
            model.price_updated_at = now if price is not None else None
        model.updated_at = now
        request.state.part_change = {
            "price_changed": price_changed,
            "old_price": old.get("price"),
            "changed": [] if is_created else [k for k in TRACKED if k in data and old[k] != data[k]],
        }

    async def after_model_change(self, data: dict[str, Any], model: Part, is_created: bool, request: Request) -> None:
        info = getattr(request.state, "part_change", None) or {}
        details: dict[str, Any] = {"changed": info.get("changed", [])}
        if info.get("price_changed"):
            details["price"] = {"old": _text(info.get("old_price")), "new": _text(model.price)}
        try:
            async with SessionLocal() as s:
                if info.get("price_changed") and model.price is not None:
                    s.add(PartPriceHistory(part_id=model.id, price=model.price, currency=model.currency,
                                           source=PRICE_SOURCE))
                s.add(_audit(request, "part.create" if is_created else "part.update", model.id, details))
                await s.commit()
        except Exception:  # деталь уже сохранена, ошибку журнала только логируем
            logger.exception("Не удалось записать историю цены или журнал для детали %s", model.id)

    async def _set_active(self, request: Request, active: bool) -> RedirectResponse:
        ids = _selected_ids(request)
        if ids:
            async with SessionLocal() as s:
                res = await s.execute(
                    update(Part).where(Part.id.in_(ids), Part.is_active != active)
                    .values(is_active=active, updated_at=func.now()).returning(Part.id)
                )
                changed = list(res.scalars())
                if changed:
                    s.add(_audit(request, "part.activate" if active else "part.deactivate",
                                 changed[0] if len(changed) == 1 else None, {"part_ids": changed}))
                await s.commit()
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)

    @action(name="deactivate", label="Снять с продажи", add_in_detail=True, add_in_list=True,
            confirmation_message="Детали пропадут из каталога и конфигуратора. "
                                 "В сохранённых сборках они будут помечены как снятые с продажи.")
    async def deactivate(self, request: Request) -> RedirectResponse:
        return await self._set_active(request, False)

    @action(name="activate", label="Вернуть в продажу", add_in_detail=True, add_in_list=True)
    async def activate(self, request: Request) -> RedirectResponse:
        return await self._set_active(request, True)


class AuditLogAdmin(ModelView, model=AuditLog):
    name = "Запись журнала"
    name_plural = "Журнал действий"
    icon = "fa-solid fa-clock-rotate-left"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [AuditLog.created_at, AuditLog.admin_id, AuditLog.action, AuditLog.entity_id,
                   AuditLog.details, AuditLog.ip_address]
    column_labels = {AuditLog.created_at: "Когда", AuditLog.admin_id: "Админ", AuditLog.action: "Действие",
                     AuditLog.entity_id: "Объект", AuditLog.details: "Подробности", AuditLog.ip_address: "IP"}
    column_sortable_list = [AuditLog.created_at]
    column_default_sort = [(AuditLog.created_at, True)]


def setup_admin(app: FastAPI) -> None:
    auth = AdminAuth(_secret(settings.secret_key))
    admin = SQLAdmin(
        app, engine, base_url=f"{settings.api_prefix}/admin", title="Конфигуратор ПК: админка",
        authentication_backend=auth, templates_dir=str(Path(__file__).parent / "templates"),
    )
    admin.add_view(PartAdmin)
    admin.add_view(AuditLogAdmin)
    ImportView.auth = auth
    admin.add_view(ImportView)