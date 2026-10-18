"""Деталь сборки в виде, удобном для расчётов. Не зависит от ORM."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class BuildPart:
    part_id: int
    category: str  # slug категории: cpu, motherboard, ram ...
    name: str
    specs: Mapping[str, Any] = field(default_factory=dict)
    power_w: int | None = None
    quantity: int = 1
    price: Decimal | None = None
