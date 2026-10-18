"""Оценка потребления сборки и рекомендуемой мощности БП.

peak_w        = base_load_w + сумма(power_w * quantity)
recommended_w = max(ceil(peak_w * factor), рекомендация производителя видеокарты)
suggested_psu_w — ближайшая стандартная мощность БП не меньше recommended_w.
"""
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from app.services.parts import BuildPart

STANDARD_PSU_W = (300, 400, 450, 500, 550, 600, 650, 700, 750, 850, 1000, 1200, 1300, 1500, 1600)
DEFAULT_BASE_LOAD_W = 50  # плата, вентиляторы, USB
DEFAULT_FACTOR = 1.3


@dataclass(frozen=True, slots=True)
class PowerEstimate:
    peak_w: int
    recommended_w: int
    suggested_psu_w: int
    base_load_w: int
    factor: float
    vendor_min_w: int | None
    by_category: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "peak_w": self.peak_w,
            "recommended_w": self.recommended_w,
            "suggested_psu_w": self.suggested_psu_w,
            "base_load_w": self.base_load_w,
            "factor": self.factor,
            "vendor_min_w": self.vendor_min_w,
            "by_category": dict(self.by_category),
        }


def _positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value > 0
    )


def suggest_psu(watts: int) -> int:
    for size in STANDARD_PSU_W:
        if size >= watts:
            return size
    return math.ceil(watts / 100) * 100


def estimate_power(
    parts: Iterable[BuildPart],
    base_load_w: float = DEFAULT_BASE_LOAD_W,
    factor: float = DEFAULT_FACTOR,
) -> PowerEstimate:
    if base_load_w < 0:
        raise ValueError("base_load_w не может быть отрицательным")
    if factor < 1:
        raise ValueError("factor должен быть не меньше 1")
    parts = list(parts)
    by_category: dict[str, int] = {}
    for p in parts:
        by_category[p.category] = by_category.get(p.category, 0) + max(p.power_w or 0, 0) * p.quantity
    base = math.ceil(base_load_w)
    peak = base + sum(by_category.values())
    # Decimal, чтобы 270 * 1.3 давало 351, а не 352 из-за погрешности float
    with_margin = int((Decimal(peak) * Decimal(str(factor))).to_integral_value(rounding=ROUND_CEILING))
    vendor = max(
        (math.ceil(p.specs["recommended_psu_w"]) for p in parts
         if p.category == "gpu" and _positive_number(p.specs.get("recommended_psu_w"))),
        default=None,
    )
    recommended = max(with_margin, vendor or 0)
    return PowerEstimate(peak, recommended, suggest_psu(recommended), base, float(factor), vendor, by_category)
