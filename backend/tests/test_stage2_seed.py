"""Стартовые данные: соответствие контракту characteristics и идемпотентность seed."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update

from app.catalog_specs import POWER_REQUIRED_CATEGORIES, REQUIRED_SPEC_KEYS
from app.models import Category, CompatibilityRule, Manufacturer, Part, PartPriceHistory
from app.scripts.seed import seed
from app.seed_data import CATEGORIES, MANUFACTURERS, PARTS, RULES, SEED_SOURCE


# ---------- Без БД: контракт данных ----------

def test_every_category_has_spec_contract():
    assert {c["slug"] for c in CATEGORIES} == set(REQUIRED_SPEC_KEYS)


@pytest.mark.parametrize("item", PARTS, ids=lambda p: p["key"])
def test_seed_part_matches_contract(item):
    missing = REQUIRED_SPEC_KEYS[item["category"]] - item["specs"].keys()
    assert not missing, f"нет ключей specs: {sorted(missing)}"
    if item["category"] in POWER_REQUIRED_CATEGORIES:
        assert item["power_w"] and item["power_w"] > 0
    assert item["price"] >= 0


def test_seed_references_and_keys_are_consistent():
    manufacturers = {m["slug"] for m in MANUFACTURERS}
    assert {p["manufacturer"] for p in PARTS} <= manufacturers
    keys = [p["key"] for p in PARTS]
    assert len(keys) == len(set(keys))
    assert len({r["code"] for r in RULES}) == len(RULES)


# ---------- С БД: идемпотентность ----------

def _count(model):
    async def go(s):
        return await s.scalar(select(func.count()).select_from(model))
    return go


@pytest.mark.db
def test_seed_first_run_loads_everything(db):
    stats = db.run(seed)
    assert stats["parts_added"] == len(PARTS)
    assert stats["prices_recorded"] == len(PARTS)
    assert db.run(_count(Category)) == len(CATEGORIES)
    assert db.run(_count(Manufacturer)) == len(MANUFACTURERS)
    assert db.run(_count(CompatibilityRule)) == len(RULES)
    assert db.run(_count(Part)) == len(PARTS)
    assert db.run(_count(PartPriceHistory)) == len(PARTS)


@pytest.mark.db
def test_seed_second_run_changes_nothing(db):
    db.run(seed)
    stats = db.run(seed)
    assert all(v == 0 for v in stats.values()), stats
    assert db.run(_count(Part)) == len(PARTS)
    assert db.run(_count(PartPriceHistory)) == len(PARTS)


@pytest.mark.db
def test_seed_restores_price_and_writes_history(db):
    db.run(seed)
    key = PARTS[0]["key"]

    async def tamper(s):
        await s.execute(update(Part).where(Part.source == SEED_SOURCE, Part.external_id == key)
                        .values(price=Decimal("1.00")))
        await s.commit()
    db.run(tamper)

    stats = db.run(seed)
    assert stats["prices_recorded"] == 1
    assert stats["parts_updated"] == 1

    async def price(s):
        return await s.scalar(select(Part.price).where(Part.external_id == key))
    assert db.run(price) == PARTS[0]["price"]
    assert db.run(_count(PartPriceHistory)) == len(PARTS) + 1


@pytest.mark.db
def test_seed_keeps_admin_rule_changes(db):
    db.run(seed)
    code = RULES[0]["code"]

    async def disable(s):
        await s.execute(update(CompatibilityRule).where(CompatibilityRule.code == code).values(is_enabled=False))
        await s.commit()
    db.run(disable)
    db.run(seed)

    async def enabled(s):
        return await s.scalar(select(CompatibilityRule.is_enabled).where(CompatibilityRule.code == code))
    assert db.run(enabled) is False
