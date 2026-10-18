"""Представление деталей и сумм для API: рубли, «ориентировочная цена», «нет данных»."""
from decimal import Decimal
from typing import Any

from app.catalog_specs import POWER_REQUIRED_CATEGORIES, REQUIRED_SPEC_KEYS, SPEC_LABELS
from app.importers.docyx import SOURCE as DOCYX_SOURCE

NO_DATA = "нет данных"
ESTIMATE_NOTE = "ориентировочная цена"
NBSP = "\u00a0"
_SIGN = {"RUB": "₽", "USD": "$", "EUR": "€"}
_UNITS = (("_mm", "мм"), ("_w", "Вт"), ("_gb", "ГБ"), ("_mhz", "МГц"))
_ORDER = {k: i for i, k in enumerate(SPEC_LABELS)}


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def format_money(value: Decimal | None, currency: str = "RUB") -> str:
    if value is None:
        return NO_DATA
    v = Decimal(value)
    text = f"{v:,.0f}" if v == v.to_integral_value() else f"{v:,.2f}"
    text = text.replace(",", NBSP).replace(".", ",")
    return f"{text}{NBSP}{_SIGN.get(currency, currency)}"


def format_spec(key: str, value: Any) -> str:
    if is_empty(value):
        return NO_DATA
    if isinstance(value, bool):
        return "есть" if value else "нет"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, (int, float, Decimal)):
        for suffix, unit in _UNITS:
            if key.endswith(suffix):
                return f"{value}{NBSP}{unit}"
        return str(value)
    return str(value)


def is_estimate(source: str | None, price: Decimal | None) -> bool:
    """Цены из датасета пересчитаны из USD, поэтому они ориентировочные."""
    return price is not None and source == DOCYX_SOURCE


def present_part(part: Any, category: str, manufacturer: str | None) -> dict[str, Any]:
    specs = dict(part.specs or {})
    required = REQUIRED_SPEC_KEYS.get(category, frozenset())
    keys = sorted(required | set(specs), key=lambda k: (_ORDER.get(k, len(_ORDER)), k))
    missing = [k for k in keys if k in required and is_empty(specs.get(k))]
    if category in POWER_REQUIRED_CATEGORIES and part.power_w is None:
        missing.append("power_w")
    estimate = is_estimate(part.source, part.price)
    return {
        "id": part.id,
        "category": category,
        "name": part.name,
        "manufacturer": manufacturer,
        "manufacturer_display": manufacturer or NO_DATA,
        "source": part.source,
        "price": None if part.price is None else str(part.price),
        "currency": part.currency,
        "has_price": part.price is not None,
        "price_display": format_money(part.price, part.currency),
        "price_is_estimate": estimate,
        "price_note": ESTIMATE_NOTE if estimate else None,
        "price_updated_at": part.price_updated_at.isoformat() if part.price_updated_at else None,
        "power_w": part.power_w,
        "power_display": NO_DATA if part.power_w is None else f"{part.power_w}{NBSP}Вт",
        "specs": specs,
        "specs_display": [
            {"key": k, "label": SPEC_LABELS.get(k, k), "value": format_spec(k, specs.get(k)),
             "missing": is_empty(specs.get(k))}
            for k in keys
        ],
        "missing_specs": missing,
        "is_data_complete": not missing and part.price is not None,
    }


def present_totals(total: Decimal | None, *, item_count: int, unpriced_count: int, estimate: bool,
                   currency: str = "RUB") -> dict[str, Any]:
    if item_count == 0:
        display = format_money(Decimal(0), currency)
    elif unpriced_count >= item_count:
        display = NO_DATA
    else:
        display = format_money(total, currency)
    notes = []
    if estimate:
        notes.append(ESTIMATE_NOTE)
    if 0 < unpriced_count < item_count:
        notes.append(f"без учёта позиций без цены: {unpriced_count}")
    return {
        "total_price_display": display,
        "total_price_is_estimate": estimate,
        "total_price_note": "; ".join(notes) or None,
        "unpriced_count": unpriced_count,
    }
