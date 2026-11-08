"""Движок совместимости. Чистые функции, без БД и сети.

Логика правил в коде, включение, severity и пороги приходят из compatibility_rules.
Нарушение "hard" получает severity правила (её может поменять админ),
"soft" (малый запас) всегда warning. Если у детали нет нужной характеристики,
правило пропускается с предупреждением missing_specs, сборка не блокируется.
Если строки правила нет в БД, оно работает со значениями из seed_data.RULES.
"""
import logging
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.models.enums import Severity
from app.seed_data import CATEGORIES, RULES
from app.services.parts import BuildPart
from app.services.power import PowerEstimate, estimate_power

logger = logging.getLogger(__name__)

STRUCTURE_RULE = "structure"
MISSING_SPECS = "missing_specs"
DEFAULT_CATEGORY_LIMITS: dict[str, int] = {c["slug"]: c["max_items"] for c in CATEGORIES}
DEFAULT_REQUIRED_CATEGORIES: tuple[str, ...] = tuple(c["slug"] for c in CATEGORIES if c["is_required"])
_RULE_DEFAULTS: dict[str, dict[str, Any]] = {r["code"]: r for r in RULES}

# Допустимые диапазоны параметров. Некорректное значение из БД заменяется значением по умолчанию
PARAM_LIMITS: dict[str, dict[str, tuple[float, float]]] = {
    "case_gpu_length": {"warning_margin_mm": (0, 200)},
    "case_cooler_height": {"warning_margin_mm": (0, 100)},
    "psu_power": {"base_load_w": (0, 500), "recommended_factor": (1.0, 3.0)},
}


@dataclass(frozen=True, slots=True)
class RuleConfig:
    code: str
    severity: Severity = Severity.ERROR
    is_enabled: bool = True
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Issue:
    rule: str
    code: str
    severity: Severity
    message: str
    part_ids: tuple[int, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule, "code": self.code, "severity": self.severity.value,
            "message": self.message, "part_ids": list(self.part_ids), "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class CheckResult:
    issues: tuple[Issue, ...]
    power: PowerEstimate
    missing_categories: tuple[str, ...]
    total_price: Decimal
    unpriced_part_ids: tuple[int, ...]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == Severity.WARNING)

    @property
    def is_compatible(self) -> bool:
        """Нет ошибок. Предупреждения сохранение не блокируют."""
        return not self.errors

    @property
    def is_complete(self) -> bool:
        """Совместима и содержит все обязательные категории."""
        return self.is_compatible and not self.missing_categories

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_compatible": self.is_compatible,
            "is_complete": self.is_complete,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
            "power": self.power.to_dict(),
            "missing_categories": list(self.missing_categories),
            "total_price": str(self.total_price),
            "unpriced_part_ids": list(self.unpriced_part_ids),
        }


# ---------- Чтение характеристик ----------

class MissingSpec(Exception):
    def __init__(self, part: BuildPart, key: str):
        super().__init__(f"{part.name}: {key}")
        self.part = part
        self.key = key


def _num(part: BuildPart, key: str) -> float:
    v = part.specs.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise MissingSpec(part, key)
    return v


def _str(part: BuildPart, key: str) -> str:
    v = part.specs.get(key)
    if not isinstance(v, str) or not v.strip():
        raise MissingSpec(part, key)
    return v.strip()


def _list(part: BuildPart, key: str) -> list[str]:
    v = part.specs.get(key)
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
        raise MissingSpec(part, key)
    return [x.strip() for x in v]


def _n(value: str) -> str:
    return value.casefold()


def _in(value: str, options: list[str]) -> bool:
    return _n(value) in {_n(o) for o in options}


def _fmt(value: float) -> str:
    return f"{value:g}"


# ---------- Правила ----------

@dataclass(frozen=True, slots=True)
class _Violation:
    hard: bool
    code: str
    message: str
    parts: tuple[BuildPart, ...]
    details: Mapping[str, Any]


def _hard(code: str, message: str, *parts: BuildPart, **details: Any) -> _Violation:
    return _Violation(True, code, message, parts, details)


def _soft(code: str, message: str, *parts: BuildPart, **details: Any) -> _Violation:
    return _Violation(False, code, message, parts, details)


class _Context:
    def __init__(self, parts: tuple[BuildPart, ...], power: PowerEstimate):
        self.parts = parts
        self.power = power
        self.by_category: dict[str, list[BuildPart]] = {}
        for p in parts:
            self.by_category.setdefault(p.category, []).append(p)

    def all(self, category: str) -> list[BuildPart]:
        return self.by_category.get(category, [])

    def one(self, category: str) -> BuildPart | None:
        items = self.by_category.get(category)
        return items[0] if items else None


Params = Mapping[str, Any]
RuleFn = Callable[[_Context, Params], Iterator[_Violation]]

def _cpu_motherboard_socket(ctx: _Context, params: Params) -> Iterator[_Violation]:
    cpu, mb = ctx.one("cpu"), ctx.one("motherboard")
    if not (cpu and mb):
        return
    a, b = _str(cpu, "socket"), _str(mb, "socket")
    if _n(a) != _n(b):
        yield _hard("socket_mismatch",
                    f"Сокет процессора {cpu.name} ({a}) не совпадает с сокетом платы {mb.name} ({b}).",
                    cpu, mb, cpu_socket=a, motherboard_socket=b)


def _ram_motherboard(ctx: _Context, params: Params) -> Iterator[_Violation]:
    rams = ctx.all("ram")
    if not rams:
        return
    cpu, mb = ctx.one("cpu"), ctx.one("motherboard")
    for ram in rams:
        t = _str(ram, "memory_type")
        if mb:
            mb_type = _str(mb, "memory_type")
            if _n(t) != _n(mb_type):
                yield _hard("ram_type_motherboard",
                            f"Плата {mb.name} поддерживает {mb_type}, а память {ram.name} — {t}.",
                            ram, mb, ram_type=t, motherboard_type=mb_type)
        if cpu:
            cpu_types = _list(cpu, "memory_types")
            if not _in(t, cpu_types):
                yield _hard("ram_type_cpu",
                            f"Процессор {cpu.name} не поддерживает {t} (поддерживает {', '.join(cpu_types)}).",
                            ram, cpu, ram_type=t, cpu_types=cpu_types)
    if mb:
        modules = sum(_num(r, "modules") * r.quantity for r in rams)
        slots = _num(mb, "memory_slots")
        if modules > slots:
            yield _hard("ram_slots_exceeded",
                        f"Выбрано {_fmt(modules)} модулей памяти, а на плате {mb.name} {_fmt(slots)} слота.",
                        *rams, mb, modules=modules, slots=slots)
        capacity = sum(_num(r, "capacity_gb") * r.quantity for r in rams)
        max_gb = _num(mb, "max_memory_gb")
        if capacity > max_gb:
            yield _hard("ram_capacity_exceeded",
                        f"Объём памяти {_fmt(capacity)} ГБ больше максимума платы {mb.name} ({_fmt(max_gb)} ГБ).",
                        *rams, mb, capacity_gb=capacity, max_memory_gb=max_gb)
    if len(rams) > 1:
        yield _soft("ram_mixed_kits",
                    "Выбраны разные комплекты памяти. Они могут не заработать на заявленной частоте, "
                    "надёжнее взять один комплект нужного объёма.", *rams)


def _case_form_factors(ctx: _Context, params: Params) -> Iterator[_Violation]:
    case = ctx.one("case")
    if not case:
        return
    mb, psu = ctx.one("motherboard"), ctx.one("psu")
    if mb:
        ff, allowed = _str(mb, "form_factor"), _list(case, "motherboard_form_factors")
        if not _in(ff, allowed):
            yield _hard("case_motherboard_form_factor",
                        f"Корпус {case.name} не поддерживает платы {ff} (поддерживает {', '.join(allowed)}).",
                        mb, case, form_factor=ff, supported=allowed)
    if psu:
        ff, allowed = _str(psu, "form_factor"), _list(case, "psu_form_factors")
        if not _in(ff, allowed):
            if _in(ff, ["SFX", "SFX-L"]) and _in("ATX", allowed):
                yield _soft("case_psu_sfx_adapter",
                            f"{psu.name} формата {ff} встанет в корпус {case.name} под ATX только через "
                            f"переходную рамку SFX→ATX. Проверьте, есть ли она в комплекте БП.",
                            psu, case)
            else:
                yield _hard("case_psu_form_factor",
                            f"Корпус {case.name} рассчитан на БП {', '.join(allowed)}, а {psu.name} — {ff}.",
                            psu, case, form_factor=ff, supported=allowed)


def _clearance(code: str, part: BuildPart, case: BuildPart, size: float, limit: float,
               margin_min: float, what: str) -> Iterator[_Violation]:
    margin = limit - size
    details = {"size_mm": size, "limit_mm": limit, "margin_mm": margin}
    if margin < 0:
        yield _hard(f"{code}_exceeded",
                    f"{what} {part.name} ({_fmt(size)} мм) не помещается в корпус {case.name} (до {_fmt(limit)} мм).",
                    part, case, **details)
    elif margin < margin_min:
        yield _soft(f"{code}_tight",
                    f"{what} {part.name} помещается в корпус {case.name} с запасом всего {_fmt(margin)} мм.",
                    part, case, **details)


def _case_gpu_length(ctx: _Context, params: Params) -> Iterator[_Violation]:
    case, gpus = ctx.one("case"), ctx.all("gpu")
    if not (case and gpus):
        return
    limit = _num(case, "max_gpu_length_mm")
    for gpu in gpus:
        yield from _clearance("gpu_length", gpu, case, _num(gpu, "length_mm"), limit,
                              params["warning_margin_mm"], "Видеокарта")


def _case_cooler_height(ctx: _Context, params: Params) -> Iterator[_Violation]:
    case, cooler = ctx.one("case"), ctx.one("cooler")
    if not (case and cooler):
        return
    yield from _clearance("cooler_height", cooler, case, _num(cooler, "height_mm"),
                          _num(case, "max_cooler_height_mm"), params["warning_margin_mm"], "Кулер")


def _cooler_socket(ctx: _Context, params: Params) -> Iterator[_Violation]:
    cpu, cooler = ctx.one("cpu"), ctx.one("cooler")
    if not (cpu and cooler):
        return
    socket, sockets = _str(cpu, "socket"), _list(cooler, "sockets")
    if not _in(socket, sockets):
        yield _hard("cooler_socket_unsupported",
                    f"Кулер {cooler.name} не поддерживает сокет {socket} (поддерживает {', '.join(sockets)}).",
                    cooler, cpu, socket=socket, supported=sockets)


def _psu_power(ctx: _Context, params: Params) -> Iterator[_Violation]:
    psu = ctx.one("psu")
    if not psu:
        return
    watts, power = _num(psu, "wattage_w"), ctx.power
    details = {"wattage_w": watts, "peak_w": power.peak_w, "recommended_w": power.recommended_w}
    if watts < power.peak_w:
        yield _hard("psu_insufficient",
                    f"Блок питания {psu.name} ({_fmt(watts)} Вт) слабее пиковой нагрузки {power.peak_w} Вт.",
                    psu, **details)
    elif watts < power.recommended_w:
        yield _soft("psu_low_headroom",
                    f"Мощности {psu.name} ({_fmt(watts)} Вт) хватает впритык. Рекомендуется от {power.recommended_w} Вт.",
                    psu, **details)


def _storage_slots(ctx: _Context, params: Params) -> Iterator[_Violation]:
    mb, drives = ctx.one("motherboard"), ctx.all("storage")
    if not (mb and drives):
        return
    counts = {"nvme": 0, "sata": 0}
    for d in drives:
        kind = _n(_str(d, "interface"))
        if kind in counts:
            counts[kind] += d.quantity
    for kind, key, code, label in (("nvme", "m2_slots", "m2_slots_exceeded", "слотов M.2"),
                                   ("sata", "sata_ports", "sata_ports_exceeded", "портов SATA")):
        if not counts[kind]:
            continue
        available = _num(mb, key)
        if counts[kind] > available:
            used = [d for d in drives if _n(_str(d, "interface")) == kind]
            yield _hard(code,
                        f"Накопителей {kind.upper()}: {counts[kind]}, а на плате {mb.name} {_fmt(available)} {label}.",
                        *used, mb, required=counts[kind], available=available)


# Порядок задаёт порядок проверок в ответе
_RULES: dict[str, RuleFn] = {
    "cpu_motherboard_socket": _cpu_motherboard_socket,
    "ram_motherboard": _ram_motherboard,
    "case_form_factors": _case_form_factors,
    "case_gpu_length": _case_gpu_length,
    "case_cooler_height": _case_cooler_height,
    "cooler_socket": _cooler_socket,
    "psu_power": _psu_power,
    "storage_slots": _storage_slots,
}
RULE_CODES: tuple[str, ...] = tuple(_RULES)


# ---------- Конфигурация ----------

def effective_params(code: str, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = _RULE_DEFAULTS[code]["params"]
    raw = raw or {}
    result: dict[str, Any] = {}
    for key, (lo, hi) in PARAM_LIMITS.get(code, {}).items():
        value = raw.get(key, defaults[key])
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and lo <= value <= hi)
        if not valid:
            logger.warning("Правило %s: некорректный параметр %s=%r, используется %r", code, key, value, defaults[key])
            value = defaults[key]
        result[key] = value
    return result


def resolve_rule(code: str, rules: Mapping[str, RuleConfig] | None) -> RuleConfig:
    cfg = rules.get(code) if rules is not None else None
    if cfg is None:
        if rules is not None:
            logger.warning("Правила %s нет в БД, используются значения по умолчанию", code)
        return RuleConfig(code, Severity(_RULE_DEFAULTS[code]["severity"]), True, effective_params(code, None))
    return RuleConfig(code, Severity(cfg.severity), cfg.is_enabled, effective_params(code, cfg.params))


def _structure_issues(ctx: _Context, limits: Mapping[str, int]) -> Iterator[Issue]:
    for category, items in ctx.by_category.items():
        ids = tuple(p.part_id for p in items)
        qty = sum(p.quantity for p in items)
        limit = limits.get(category)
        if limit is None:
            yield Issue(STRUCTURE_RULE, "unknown_category", Severity.ERROR,
                        f"Неизвестная категория {category}.", ids, {"category": category})
        elif qty > limit:
            yield Issue(STRUCTURE_RULE, "category_limit_exceeded", Severity.ERROR,
                        f"В категории {category} выбрано {qty} шт., допустимо не больше {limit}.",
                        ids, {"category": category, "quantity": qty, "limit": limit})


def check_build(
    parts: Sequence[BuildPart],
    rules: Mapping[str, RuleConfig] | None = None,
    *,
    category_limits: Mapping[str, int] | None = None,
    required_categories: Sequence[str] | None = None,
) -> CheckResult:
    """rules=None — все правила со значениями по умолчанию (для тестов и резервного режима)."""
    parts = tuple(parts)
    limits = DEFAULT_CATEGORY_LIMITS if category_limits is None else category_limits
    required = DEFAULT_REQUIRED_CATEGORIES if required_categories is None else tuple(required_categories)
    configs = {code: resolve_rule(code, rules) for code in _RULES}
    pp = configs["psu_power"].params
    power = estimate_power(parts, base_load_w=pp["base_load_w"], factor=pp["recommended_factor"])
    ctx = _Context(parts, power)

    issues = list(_structure_issues(ctx, limits))
    for code, fn in _RULES.items():
        cfg = configs[code]
        if not cfg.is_enabled:
            continue
        try:
            for v in fn(ctx, cfg.params):
                issues.append(Issue(code, v.code, cfg.severity if v.hard else Severity.WARNING, v.message,
                                    tuple(dict.fromkeys(p.part_id for p in v.parts)), dict(v.details)))
        except MissingSpec as exc:
            issues.append(Issue(
                code, MISSING_SPECS, Severity.WARNING,
                f"Проверка «{_RULE_DEFAULTS[code]['name']}» пропущена: у {exc.part.name} не указано {exc.key}.",
                (exc.part.part_id,), {"key": exc.key},
            ))
    issues.sort(key=lambda i: i.severity != Severity.ERROR)  # сортировка стабильная: ошибки первыми

    present = {p.category for p in parts}
    total = sum((p.price * p.quantity for p in parts if p.price is not None), Decimal("0"))
    return CheckResult(
        issues=tuple(issues),
        power=power,
        missing_categories=tuple(c for c in required if c not in present),
        total_price=total,
        unpriced_part_ids=tuple(p.part_id for p in parts if p.price is None),
    )
