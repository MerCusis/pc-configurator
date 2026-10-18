"""Импорт каталога из датасета github.com/docyx/pc-part-dataset (данные PCPartPicker).

В датасете нет части полей, нужных движку совместимости: сокетов и высоты кулеров,
максимальной длины видеокарты в корпусе, числа слотов M.2 и портов SATA. Такие ключи
не заполняются, а не угадываются: движок выдаёт по ним предупреждение missing_specs
вместо ложной ошибки. Сокет процессора выводится из микроархитектуры, тип памяти
платы из сокета, потребление CPU и GPU оценивается (specs.power_estimated = true).

Импортируются только актуальные платформы: AM4, AM5, LGA1200, LGA1700, LGA1851.
Цены в датасете в долларах США; при заданном курсе пересчитываются в рубли.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

SOURCE = "docyx"
DATASET_URL = "https://github.com/docyx/pc-part-dataset"
RAW_URL = "https://raw.githubusercontent.com/docyx/pc-part-dataset/{ref}/data/json/{file}.json"
LOCK_KEY = 0x646F6379  # advisory lock: два импорта одновременно не пойдут

# slug категории в нашей БД -> имя файла в датасете
FILES: dict[str, str] = {
    "cpu": "cpu", "motherboard": "motherboard", "ram": "memory", "gpu": "video-card",
    "storage": "internal-hard-drive", "psu": "power-supply", "case": "case", "cooler": "cpu-cooler",
}

SUPPORTED_SOCKETS = ("AM4", "AM5", "LGA1200", "LGA1700", "LGA1851")
SOCKET_MEMORY: dict[str, tuple[str, ...]] = {
    "AM4": ("DDR4",), "AM5": ("DDR5",), "LGA1200": ("DDR4",),
    "LGA1700": ("DDR4", "DDR5"), "LGA1851": ("DDR5",),
}
ARCH_SOCKET: dict[str, str] = {
    "Zen 5": "AM5", "Zen 4": "AM5", "Zen 3": "AM4", "Zen 2": "AM4", "Zen+": "AM4", "Zen": "AM4",
    "Arrow Lake": "LGA1851", "Raptor Lake Refresh": "LGA1700", "Raptor Lake": "LGA1700",
    "Alder Lake": "LGA1700", "Rocket Lake": "LGA1200", "Comet Lake": "LGA1200",
}
# Пиковое потребление относительно TDP: AMD PPT ~1.35, Intel PL2 до 2x
CPU_POWER_FACTOR = {"AM4": 1.35, "AM5": 1.35, "LGA1200": 1.6, "LGA1700": 2.0, "LGA1851": 2.0}
CPU_POWER_CAP_W = 253

# Порядок важен: более длинные названия раньше (4070 Ti раньше 4070, XTX раньше XT)
GPU_TDP: list[tuple[str, int]] = [
    ("RTX 5090", 575), ("RTX 5080", 360), ("RTX 5070 Ti", 300), ("RTX 5070", 250),
    ("RTX 5060 Ti", 180), ("RTX 5060", 145), ("RTX 5050", 130),
    ("RTX 4090", 450), ("RTX 4080", 320), ("RTX 4070 Ti", 285), ("RTX 4070 SUPER", 220), ("RTX 4070", 200),
    ("RTX 4060 Ti", 165), ("RTX 4060", 115),
    ("RTX 3090 Ti", 450), ("RTX 3090", 350), ("RTX 3080 Ti", 350), ("RTX 3080", 320), ("RTX 3070 Ti", 290),
    ("RTX 3070", 220), ("RTX 3060 Ti", 200), ("RTX 3060", 170), ("RTX 3050", 130),
    ("RTX 2080 Ti", 250), ("RTX 2080", 215), ("RTX 2070", 175), ("RTX 2060", 160),
    ("GTX 1660", 125), ("GTX 1650", 75), ("GT 1030", 30), ("GT 730", 38), ("GT 710", 19),
    ("RX 9070 XT", 304), ("RX 9070", 220), ("RX 9060 XT", 160),
    ("RX 7900 XTX", 355), ("RX 7900 XT", 315), ("RX 7900 GRE", 260), ("RX 7800 XT", 263),
    ("RX 7700 XT", 245), ("RX 7600 XT", 190), ("RX 7600", 165),
    ("RX 6950 XT", 335), ("RX 6900 XT", 300), ("RX 6800 XT", 300), ("RX 6800", 250), ("RX 6750 XT", 250),
    ("RX 6700 XT", 230), ("RX 6700", 175), ("RX 6650 XT", 180), ("RX 6600 XT", 160), ("RX 6600", 132),
    ("RX 6500 XT", 107), ("RX 6400", 53),
    ("Arc B580", 190), ("Arc B570", 150), ("Arc A770", 225), ("Arc A750", 225), ("Arc A580", 185), ("Arc A380", 75),
]
_GPU_PATTERNS = [(re.compile(re.escape(n) + r"(?![\w])", re.I), w) for n, w in GPU_TDP]

MB_FORM_FACTORS = {"ATX": "ATX", "Micro ATX": "Micro-ATX", "Mini ITX": "Mini-ITX", "EATX": "E-ATX"}
PSU_FORM_FACTORS = {"ATX": "ATX", "SFX": "SFX", "SFX-L": "SFX-L"}
_DDR4_HINT = re.compile(r"DDR4|\bD4\b", re.I)
_CPU_EXCLUDE = re.compile(r"threadripper|epyc|xeon", re.I)

TWO_WORD_BRANDS = ("be quiet!", "cooler master", "fractal design", "western digital", "lian li",
                   "silicon power", "super flower", "team group")
SLUG_ALIASES = {"g.skill": "gskill", "be quiet!": "be-quiet", "cooler master": "cooler-master",
                "fractal design": "fractal"}
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,64}$")


class Skip(Exception):
    """Запись не подходит для каталога; reason попадает в статистику."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ImportBusyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MappedPart:
    category: str
    external_id: str
    name: str
    manufacturer: tuple[str, str] | None  # (slug, name)
    specs: dict[str, Any]
    power_w: int | None
    price_usd: Decimal | None


# ---------- разбор значений ----------

def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or v < 0:
        return None
    return v


def _int(v: Any) -> int | None:
    n = _num(v)
    return None if n is None else int(round(n))


def _max_num(v: Any) -> float | None:
    """rpm и noise бывают числом или диапазоном [min, max]."""
    if isinstance(v, list):
        nums = [n for n in map(_num, v) if n is not None]
        return max(nums) if nums else None
    return _num(v)


def _pair(v: Any) -> tuple[float, float] | None:
    if isinstance(v, list) and len(v) == 2 and all(_num(x) is not None for x in v):
        return v[0], v[1]
    return None


def _str(v: Any) -> str | None:
    return v.strip()[:64] if isinstance(v, str) and v.strip() else None


def _clean(specs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in specs.items() if v is not None}


def _price(v: Any) -> Decimal | None:
    n = _num(v)
    if not n:
        return None
    return Decimal(str(n)).quantize(Decimal("0.01"))


def gpu_tdp(chipset: str) -> int | None:
    for pattern, watts in _GPU_PATTERNS:
        if pattern.search(chipset):
            return watts
    return None


def manufacturer_of(name: str) -> tuple[str, str] | None:
    low = name.lower()
    raw = next((name[: len(b)] for b in TWO_WORD_BRANDS if low == b or low.startswith(b + " ")), None)
    if raw is None:
        raw = name.split()[0] if name.split() else ""
    slug = SLUG_ALIASES.get(raw.lower()) or re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return (slug[:64], raw[:64]) if slug else None


def external_id(file: str, rec: dict[str, Any]) -> str:
    """Стабильный ID: хеш записи без цены, чтобы смена цены не плодила дубли."""
    core = {k: v for k, v in rec.items() if k not in ("price", "price_per_gb")}
    digest = hashlib.sha1(json.dumps(core, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    return f"{file}:{digest}"


def _capacity_label(gb: int) -> str:
    return f"{gb // 1000} ТБ" if gb >= 1000 and gb % 1000 == 0 else f"{gb} ГБ"


# ---------- маппинг категорий: (specs, power_w, дополнение к названию) ----------

Mapped = tuple[dict[str, Any], int | None, str | None]


def map_cpu(rec: dict[str, Any]) -> Mapped:
    if _CPU_EXCLUDE.search(rec["name"]):
        raise Skip("unsupported_platform")
    socket = ARCH_SOCKET.get(rec.get("microarchitecture") or "")
    if socket is None:
        raise Skip("unsupported_platform")
    tdp = _int(rec.get("tdp"))
    if not tdp:
        raise Skip("missing_tdp")
    power = max(tdp, min(round(tdp * CPU_POWER_FACTOR[socket]), CPU_POWER_CAP_W))
    specs = _clean({
        "socket": socket, "memory_types": list(SOCKET_MEMORY[socket]), "tdp_w": tdp,
        "integrated_graphics": bool(rec.get("graphics")), "graphics": _str(rec.get("graphics")),
        "cores": _int(rec.get("core_count")), "base_clock_ghz": _num(rec.get("core_clock")),
        "boost_clock_ghz": _num(rec.get("boost_clock")), "microarchitecture": rec.get("microarchitecture"),
        "power_estimated": True,
    })
    return specs, power, None


def map_motherboard(rec: dict[str, Any]) -> Mapped:
    socket = rec.get("socket")
    if socket not in SUPPORTED_SOCKETS:
        raise Skip("unsupported_platform")
    ff = MB_FORM_FACTORS.get(rec.get("form_factor") or "")
    if ff is None:
        raise Skip("unsupported_form_factor")
    memory = SOCKET_MEMORY[socket]
    # LGA1700 бывает и DDR4, и DDR5: DDR4-версии помечены в названии (DDR4 / D4)
    mtype = ("DDR4" if _DDR4_HINT.search(rec["name"]) else "DDR5") if len(memory) > 1 else memory[0]
    specs = _clean({
        "socket": socket, "form_factor": ff, "memory_type": mtype,
        "memory_slots": _int(rec.get("memory_slots")), "max_memory_gb": _int(rec.get("max_memory")),
        "color": _str(rec.get("color")),
    })
    return specs, None, None


def map_ram(rec: dict[str, Any]) -> Mapped:
    speed, modules = _pair(rec.get("speed")), _pair(rec.get("modules"))
    if not speed or int(speed[0]) not in (4, 5):
        raise Skip("unsupported_memory_type")
    if not modules or int(modules[0]) < 1 or int(modules[1]) < 1:
        raise Skip("missing_modules")
    gen, mhz, n, size = int(speed[0]), int(speed[1]), int(modules[0]), int(modules[1])
    specs = _clean({
        "memory_type": f"DDR{gen}", "speed_mhz": mhz, "modules": n, "module_gb": size,
        "capacity_gb": n * size, "cas_latency": _num(rec.get("cas_latency")), "color": _str(rec.get("color")),
    })
    return specs, 4 * n, f"DDR{gen}-{mhz} ({n}x{size} ГБ)"


def map_gpu(rec: dict[str, Any]) -> Mapped:
    chipset = rec.get("chipset") or ""
    tdp = gpu_tdp(chipset)
    if tdp is None:
        raise Skip("unknown_gpu_chipset")
    specs = _clean({
        "chipset": chipset, "memory_gb": _int(rec.get("memory")), "length_mm": _int(rec.get("length")),
        "core_clock_mhz": _int(rec.get("core_clock")), "boost_clock_mhz": _int(rec.get("boost_clock")),
        "tdp_w": tdp, "recommended_psu_w": math.ceil((tdp * 1.6 + 300) / 50) * 50,
        "color": _str(rec.get("color")), "power_estimated": True,
    })
    extra = None if chipset.lower() in rec["name"].lower() else chipset
    return specs, tdp, extra


def map_storage(rec: dict[str, Any]) -> Mapped:
    bus = rec.get("interface") or ""
    if bus.startswith("M.2 PCIe"):
        interface = "nvme"
    elif bus.startswith("SATA"):
        interface = "sata"
    else:
        raise Skip("unsupported_interface")  # M.2 SATA, U.2, PCIe-карты
    capacity = _int(rec.get("capacity"))
    if not capacity:
        raise Skip("missing_capacity")
    kind = "ssd" if rec.get("type") == "SSD" else "hdd"
    specs = _clean({
        "interface": interface, "bus": bus, "capacity_gb": capacity, "kind": kind,
        "rpm": _int(rec.get("type")) if kind == "hdd" else None,
        "form_factor": _str(str(rec["form_factor"])) if rec.get("form_factor") is not None else None,
        "cache_mb": _int(rec.get("cache")),
    })
    return specs, 6 if kind == "ssd" else 9, _capacity_label(capacity)


def map_psu(rec: dict[str, Any]) -> Mapped:
    ff = PSU_FORM_FACTORS.get(rec.get("type") or "")
    if ff is None:
        raise Skip("unsupported_form_factor")
    watts = _int(rec.get("wattage"))
    if not watts:
        raise Skip("missing_wattage")
    specs = _clean({
        "wattage_w": watts, "form_factor": ff, "efficiency": _str(rec.get("efficiency")),
        "modular": _str(rec.get("modular")), "color": _str(rec.get("color")),
    })
    return specs, None, None


def map_case(rec: dict[str, Any]) -> Mapped:
    t = rec.get("type") or ""
    if t.startswith("ATX"):
        boards = ["ATX", "Micro-ATX", "Mini-ITX"] + (["E-ATX"] if "Full Tower" in t else [])
    elif t.startswith("MicroATX"):
        boards = ["Micro-ATX", "Mini-ITX"]
    elif t.startswith("Mini ITX"):
        boards = ["Mini-ITX"]
    else:
        raise Skip("unsupported_case_type")
    # У компактных корпусов формат БП в датасете не указан: не угадываем
    psu = ["ATX", "SFX", "SFX-L"] if "Tower" in t and not t.startswith("Mini ITX") else None
    specs = _clean({
        "motherboard_form_factors": boards, "psu_form_factors": psu, "case_type": t,
        "side_panel": _str(rec.get("side_panel")), "volume_l": _num(rec.get("external_volume")),
        "bays_35": _int(rec.get("internal_35_bays")), "included_psu_w": _int(rec.get("psu")),
        "color": _str(rec.get("color")),
    })
    return specs, None, None


def map_cooler(rec: dict[str, Any]) -> Mapped:
    radiator = _int(rec.get("size"))
    specs = _clean({
        "type": "aio" if radiator else "air", "radiator_mm": radiator,
        "max_rpm": _int(_max_num(rec.get("rpm"))), "noise_db": _max_num(rec.get("noise_level")),
        "color": _str(rec.get("color")),
    })
    return specs, 15 if radiator else 4, None


MAPPERS: dict[str, Callable[[dict[str, Any]], Mapped]] = {
    "cpu": map_cpu, "motherboard": map_motherboard, "ram": map_ram, "gpu": map_gpu,
    "storage": map_storage, "psu": map_psu, "case": map_case, "cooler": map_cooler,
}


def map_records(category: str, records: Iterable[Any], *, include_unpriced: bool = False
                ) -> tuple[list[MappedPart], Counter]:
    file, mapper = FILES[category], MAPPERS[category]
    out: dict[str, MappedPart] = {}
    skipped: Counter = Counter()
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get("name"), str) or not rec["name"].strip():
            skipped["invalid_record"] += 1
            continue
        price = _price(rec.get("price"))
        if price is None and not include_unpriced:
            skipped["no_price"] += 1
            continue
        try:
            specs, power, extra = mapper(rec)
        except Skip as exc:
            skipped[exc.reason] += 1
            continue
        base = " ".join(rec["name"].split())
        name = f"{base} {extra}" if extra else base
        eid = external_id(file, rec)
        prev = out.get(eid)
        if prev is not None:
            skipped["duplicate"] += 1
            if price is not None and (prev.price_usd is None or price < prev.price_usd):
                out[eid] = replace(prev, price_usd=price)
            continue
        out[eid] = MappedPart(category, eid, name[:255], manufacturer_of(base), specs, power, price)
    return list(out.values()), skipped


# ---------- загрузка ----------

def load_dataset(path: Path | None = None, *, ref: str = "main", categories: Iterable[str] | None = None,
                 timeout: float = 60) -> dict[str, list[Any]]:
    """Из локальной копии репозитория (path) или с raw.githubusercontent.com (ref: ветка или коммит)."""
    cats = list(categories or FILES)
    unknown = [c for c in cats if c not in FILES]
    if unknown:
        raise ValueError(f"Неизвестные категории: {', '.join(unknown)}")
    if path is not None and (path / "data" / "json").is_dir():
        path = path / "data" / "json"
    if path is None and not _REF_RE.fullmatch(ref):
        raise ValueError("Некорректный ref")
    data: dict[str, list[Any]] = {}
    for cat in cats:
        file = FILES[cat]
        if path is not None:
            raw = json.loads((path / f"{file}.json").read_text(encoding="utf-8"))
        else:
            url = RAW_URL.format(ref=urllib.parse.quote(ref, safe="/"), file=file)
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (фиксированный https-хост)
                raw = json.load(resp)
        if not isinstance(raw, list):
            raise ValueError(f"{file}.json: ожидался JSON-массив")
        data[cat] = raw
    return data


def _chunks(items: list[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ---------- запись в БД ----------

async def import_catalog(session, data: dict[str, list[Any]], *, usd_rate: Decimal | None = None,
                         include_unpriced: bool = False, retire_missing: bool = True,
                         retire_seed: bool = False) -> dict[str, Any]:
    """Upsert по (source, external_id), история цен, деактивация исчезнувших. Commit делает вызывающий."""
    from sqlalchemy import case, func, insert, select, text, true, update
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models import Category, Manufacturer, Part, PartPriceHistory

    if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}):
        raise ImportBusyError("Импорт каталога уже выполняется")
    if usd_rate is not None and usd_rate <= 0:
        raise ValueError("Курс должен быть больше нуля")

    currency = "RUB" if usd_rate else "USD"
    cat_ids = dict((await session.execute(select(Category.slug, Category.id))).all())
    stats: dict[str, Any] = {"source": SOURCE, "currency": currency,
                             "usd_rate": str(usd_rate) if usd_rate else None, "categories": {},
                             "created": 0, "updated": 0, "price_changes": 0, "retired": 0, "seed_retired": 0}
    mapped: list[MappedPart] = []
    for cat, records in data.items():
        if cat not in cat_ids:
            raise ValueError(f"Категории {cat} нет в БД. Сначала выполните seed")
        parts, skipped = map_records(cat, records, include_unpriced=include_unpriced)
        stats["categories"][cat] = {"read": len(records), "imported": len(parts), "skipped": dict(skipped)}
        mapped.extend(parts)

    makers = {m.manufacturer[0]: m.manufacturer[1] for m in mapped if m.manufacturer}
    for chunk in _chunks(sorted(makers.items()), 1000):
        await session.execute(pg_insert(Manufacturer).values([{"slug": s, "name": n} for s, n in chunk])
                              .on_conflict_do_nothing(index_elements=["slug"]))
    maker_ids = dict((await session.execute(select(Manufacturer.slug, Manufacturer.id))).all())
    existing = {eid: (pid, price) for eid, pid, price in (await session.execute(
        select(Part.external_id, Part.id, Part.price).where(Part.source == SOURCE))).all()}

    def convert(p: Decimal | None) -> Decimal | None:
        if p is None or usd_rate is None:
            return p
        return (p * usd_rate).quantize(Decimal("1"), ROUND_HALF_UP)

    rows = [{
        "category_id": cat_ids[m.category], "manufacturer_id": maker_ids.get(m.manufacturer[0]) if m.manufacturer else None,
        "name": m.name, "source": SOURCE, "external_id": m.external_id, "specs": m.specs,
        "power_w": m.power_w, "price": convert(m.price_usd), "currency": currency,
    } for m in mapped]
    by_eid = {r["external_id"]: r for r in rows}
    table = Part.__table__

    for chunk in _chunks(rows, 500):
        stmt = pg_insert(Part).values(chunk)
        ex = stmt.excluded
        set_ = {
            "category_id": ex.category_id, "manufacturer_id": ex.manufacturer_id, "name": ex.name,
            "specs": ex.specs, "power_w": ex.power_w, "price": ex.price, "currency": ex.currency,
            "is_active": true(),
            "price_updated_at": case((table.c.price.is_distinct_from(ex.price), func.now()),
                                     else_=table.c.price_updated_at),
        }
        if "updated_at" in table.c:
            set_["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=["source", "external_id"], set_=set_)
        result = (await session.execute(stmt.returning(table.c.id, table.c.external_id))).all()
        history = []
        for pid, eid in result:
            prev, row = existing.get(eid), by_eid[eid]
            stats["created" if prev is None else "updated"] += 1
            if row["price"] is not None and (prev is None or prev[1] != row["price"]):
                history.append({"part_id": pid, "price": row["price"], "currency": currency, "source": SOURCE})
                if prev is not None:
                    stats["price_changes"] += 1
        if history:
            await session.execute(insert(PartPriceHistory), history)

    await session.execute(update(Part).where(Part.source == SOURCE, Part.price.is_not(None),
                                             Part.price_updated_at.is_(None)).values(price_updated_at=func.now()))
    if retire_missing:
        for cat in data:
            seen = [r["external_id"] for r in rows if r["category_id"] == cat_ids[cat]]
            cond = [Part.source == SOURCE, Part.category_id == cat_ids[cat], Part.is_active.is_(True)]
            if seen:
                cond.append(Part.external_id.not_in(seen))
            res = await session.execute(update(Part).where(*cond).values(is_active=False))
            stats["retired"] += res.rowcount or 0
    if retire_seed:
        res = await session.execute(update(Part).where(Part.source == "seed", Part.is_active.is_(True))
                                    .values(is_active=False))
        stats["seed_retired"] = res.rowcount or 0
    return stats
