"""Этап 4: маппинг датасета docyx и импорт в PostgreSQL."""
import asyncio
import copy
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.importers.docyx import (
    SOURCE, external_id, gpu_tdp, import_catalog, manufacturer_of, map_records,
)
from app.models import Part, PartPriceHistory
from app.models.enums import Severity
from app.scripts.seed import seed
from app.services.build_check import check_items

CPU = [
    {"name": "AMD Ryzen 7 9800X3D", "price": 451.5, "core_count": 8, "core_clock": 4.7, "boost_clock": 5.2,
     "microarchitecture": "Zen 5", "tdp": 120, "graphics": "Radeon"},
    {"name": "AMD Ryzen 5 5600X", "price": 120.0, "core_count": 6, "core_clock": 3.7, "boost_clock": 4.6,
     "microarchitecture": "Zen 3", "tdp": 65, "graphics": None},
]
MB = [{"name": "MSI B650 GAMING PLUS WIFI", "price": 169.99, "socket": "AM5", "form_factor": "ATX",
       "max_memory": 192, "memory_slots": 4, "color": "Black"}]
RAM = [{"name": "G.Skill Flare X5 32 GB", "price": 89.99, "speed": [5, 6000], "modules": [2, 16],
        "price_per_gb": 2.812, "color": "Black", "first_word_latency": 12, "cas_latency": 36}]
SAMPLE = {"cpu": CPU, "motherboard": MB, "ram": RAM}


def one(category, rec, **kw):
    parts, skipped = map_records(category, [rec], **kw)
    return (parts[0] if parts else None), skipped


# ---------- маппинг без БД ----------

def test_cpu_socket_and_power_from_architecture():
    p, _ = one("cpu", CPU[0])
    assert p.specs["socket"] == "AM5" and p.specs["memory_types"] == ["DDR5"]
    assert p.specs["integrated_graphics"] is True and p.power_w == 162
    intel, _ = one("cpu", {**CPU[1], "name": "Intel Core i9-14900K", "microarchitecture": "Raptor Lake Refresh",
                           "tdp": 125, "graphics": "Intel UHD Graphics 770"})
    assert intel.specs["socket"] == "LGA1700" and intel.specs["memory_types"] == ["DDR4", "DDR5"]
    assert intel.power_w == 250


def test_cpu_unsupported_platforms_skipped():
    for rec in ({**CPU[0], "name": "AMD Ryzen Threadripper 7980X"}, {**CPU[0], "microarchitecture": "Skylake"}):
        p, skipped = one("cpu", rec)
        assert p is None and skipped["unsupported_platform"] == 1


def test_motherboard_memory_type_for_lga1700():
    base = {"price": 150, "socket": "LGA1700", "form_factor": "Micro ATX", "max_memory": 128, "memory_slots": 4}
    for name, expected in (("MSI PRO B760M-A DDR4", "DDR4"), ("Asus PRIME B760M-A D4", "DDR4"),
                           ("MSI PRO Z790-A WIFI", "DDR5")):
        p, _ = one("motherboard", {**base, "name": name})
        assert p.specs["memory_type"] == expected and p.specs["form_factor"] == "Micro-ATX"
    p, skipped = one("motherboard", {**base, "name": "Old", "socket": "LGA1151"})
    assert p is None and skipped["unsupported_platform"] == 1


def test_ram_kit():
    p, _ = one("ram", RAM[0])
    assert p.specs == {"memory_type": "DDR5", "speed_mhz": 6000, "modules": 2, "module_gb": 16,
                       "capacity_gb": 32, "cas_latency": 36, "color": "Black"}
    assert p.name == "G.Skill Flare X5 32 GB DDR5-6000 (2x16 ГБ)" and p.power_w == 8
    assert p.manufacturer == ("gskill", "G.Skill")
    p, skipped = one("ram", {**RAM[0], "speed": [3, 1600]})
    assert p is None and skipped["unsupported_memory_type"] == 1


def test_gpu_tdp_table_and_name():
    assert gpu_tdp("Radeon RX 7900 XTX") == 355 and gpu_tdp("Radeon RX 7900 XT") == 315
    assert gpu_tdp("GeForce RTX 4070 Ti SUPER") == 285 and gpu_tdp("GeForce RTX 4070") == 200
    assert gpu_tdp("GeForce RTX 3060 12GB") == 170 and gpu_tdp("Radeon HD 5450") is None
    p, _ = one("gpu", {"name": "Sapphire PULSE", "price": 379.99, "chipset": "Radeon RX 9060 XT", "memory": 16,
                       "core_clock": 2220, "boost_clock": 3290, "color": "Black", "length": 240})
    assert p.name == "Sapphire PULSE Radeon RX 9060 XT"
    assert p.specs["length_mm"] == 240 and p.specs["tdp_w"] == 160 and p.specs["recommended_psu_w"] == 600


def test_storage_interfaces():
    base = {"name": "Samsung 990 Pro", "price": 149.99, "capacity": 2000, "type": "SSD", "cache": 2048,
            "form_factor": "M.2-2280", "interface": "M.2 PCIe 4.0 X4"}
    p, _ = one("storage", base)
    assert p.specs["interface"] == "nvme" and p.name == "Samsung 990 Pro 2 ТБ"
    p, _ = one("storage", {**base, "type": 7200, "interface": "SATA 6.0 Gb/s", "form_factor": 3.5, "capacity": 4000})
    assert p.specs["interface"] == "sata" and p.specs["kind"] == "hdd" and p.specs["rpm"] == 7200
    p, skipped = one("storage", {**base, "interface": "M.2 SATA"})
    assert p is None and skipped["unsupported_interface"] == 1


def test_case_and_psu_and_cooler():
    p, _ = one("case", {"name": "Phanteks XT PRO", "price": 67.98, "type": "ATX Mid Tower", "color": "Black",
                        "psu": None, "side_panel": "Tempered Glass", "external_volume": 51.8, "internal_35_bays": 2})
    assert p.specs["motherboard_form_factors"] == ["ATX", "Micro-ATX", "Mini-ITX"]
    assert "max_gpu_length_mm" not in p.specs  # нет в датасете, не угадываем
    itx, _ = one("case", {"name": "X", "price": 99, "type": "Mini ITX Desktop"})
    assert itx.specs["motherboard_form_factors"] == ["Mini-ITX"] and "psu_form_factors" not in itx.specs
    psu, _ = one("psu", {"name": "MSI MAG A750GL PCIE5", "price": 109.99, "type": "ATX", "efficiency": "gold",
                         "wattage": 750, "modular": "Full", "color": "Black"})
    assert psu.specs["wattage_w"] == 750 and psu.specs["form_factor"] == "ATX"
    aio, _ = one("cooler", {"name": "ARCTIC Liquid Freezer III Pro 360", "price": 84.99, "rpm": [600, 3000],
                            "noise_level": None, "color": "Black", "size": 360})
    assert aio.specs == {"type": "aio", "radiator_mm": 360, "max_rpm": 3000, "color": "Black"}


def test_unpriced_duplicates_and_stable_id():
    unpriced = {**CPU[0], "price": None}
    parts, skipped = map_records("cpu", [unpriced])
    assert parts == [] and skipped["no_price"] == 1
    parts, _ = map_records("cpu", [unpriced], include_unpriced=True)
    assert parts[0].price_usd is None
    parts, skipped = map_records("cpu", [CPU[0], {**CPU[0], "price": 399.0}])
    assert len(parts) == 1 and parts[0].price_usd == Decimal("399.00") and skipped["duplicate"] == 1
    assert external_id("cpu", CPU[0]) == external_id("cpu", {**CPU[0], "price": 1})
    assert manufacturer_of("be quiet! Pure Power 12") == ("be-quiet", "be quiet!")
    assert manufacturer_of("Cooler Master MasterBox") == ("cooler-master", "Cooler Master")


# ---------- импорт в PostgreSQL ----------

@pytest.fixture
def seeded(db):
    db.run(seed)
    return db


def imp(db, data, **kw):
    async def go(session):
        stats = await import_catalog(session, data, **kw)
        await session.commit()
        return stats
    return db.run(go)


def scalar(db, stmt):
    async def go(session):
        return await session.scalar(stmt)
    return db.run(go)


def part_by_name(db, name):
    return scalar(db, select(Part).where(Part.source == SOURCE, Part.name == name))


@pytest.mark.db
def test_import_is_idempotent(seeded):
    s1 = imp(seeded, SAMPLE)
    assert (s1["created"], s1["updated"], s1["currency"]) == (4, 0, "USD")
    s2 = imp(seeded, SAMPLE)
    assert (s2["created"], s2["updated"], s2["price_changes"], s2["retired"]) == (0, 4, 0, 0)
    assert scalar(seeded, select(func.count()).select_from(Part).where(Part.source == SOURCE)) == 4
    assert scalar(seeded, select(func.count()).select_from(PartPriceHistory)
                  .where(PartPriceHistory.source == SOURCE)) == 4
    p = part_by_name(seeded, "AMD Ryzen 7 9800X3D")
    assert p.price == Decimal("451.50") and p.price_updated_at is not None and p.manufacturer_id is not None


@pytest.mark.db
def test_price_change_and_retire_missing(seeded):
    imp(seeded, SAMPLE)
    changed = copy.deepcopy(SAMPLE)
    changed["cpu"][0]["price"] = 399.99
    del changed["cpu"][1]
    s = imp(seeded, changed)
    assert s["price_changes"] == 1 and s["retired"] == 1
    cpu = part_by_name(seeded, "AMD Ryzen 7 9800X3D")
    assert scalar(seeded, select(func.count()).select_from(PartPriceHistory)
                  .where(PartPriceHistory.part_id == cpu.id)) == 2
    assert part_by_name(seeded, "AMD Ryzen 5 5600X").is_active is False
    s = imp(seeded, SAMPLE)  # вернулась в датасет — снова активна
    assert part_by_name(seeded, "AMD Ryzen 5 5600X").is_active is True


@pytest.mark.db
def test_rub_conversion_and_retire_seed(seeded):
    s = imp(seeded, SAMPLE, usd_rate=Decimal("80"), retire_seed=True)
    assert s["currency"] == "RUB" and s["seed_retired"] == 33
    p = part_by_name(seeded, "AMD Ryzen 7 9800X3D")
    assert p.price == Decimal("36120") and p.currency == "RUB"
    assert scalar(seeded, select(func.count()).select_from(Part)
                  .where(Part.source == "seed", Part.is_active.is_(True))) == 0


@pytest.mark.db
def test_imported_parts_work_with_engine(seeded):
    imp(seeded, SAMPLE)
    ids = {n: part_by_name(seeded, n).id for n in
           ("AMD Ryzen 7 9800X3D", "AMD Ryzen 5 5600X", "MSI B650 GAMING PLUS WIFI",
            "G.Skill Flare X5 32 GB DDR5-6000 (2x16 ГБ)")}

    def check(names):
        async def go(session):
            return await check_items(session, [(ids[n], 1) for n in names])
        return seeded.run(go)

    ok = check(["AMD Ryzen 7 9800X3D", "MSI B650 GAMING PLUS WIFI", "G.Skill Flare X5 32 GB DDR5-6000 (2x16 ГБ)"])
    assert not ok.errors, [i.code for i in ok.errors]
    bad = check(["AMD Ryzen 5 5600X", "MSI B650 GAMING PLUS WIFI"])
    assert "socket_mismatch" in {i.code for i in bad.errors}
