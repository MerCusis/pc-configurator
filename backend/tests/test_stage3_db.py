"""Этап 3: проверка сборки с правилами, категориями и деталями из PostgreSQL."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from app.models import CompatibilityRule, Part
from app.models.enums import Severity
from app.scripts.seed import seed
from app.seed_data import SEED_SOURCE
from app.services.build_check import UnknownPartsError, check_items

pytestmark = pytest.mark.db

BASE = ["amd-ryzen5-7600", "msi-b650-gaming-plus-wifi", "kingston-fury-ddr5-32-6000", "palit-rtx4060-dual",
        "samsung-990pro-1tb", "deepcool-pk650d", "bequiet-pure-base-500", "deepcool-ak400"]


@pytest.fixture
def seeded(db):
    db.run(seed)
    return db


def run(db, keys, before=None, qty=None):
    """keys: external_id деталей; qty: {external_id: количество}, по умолчанию 1."""
    qty = qty or {}

    async def go(session):
        if before is not None:
            await session.execute(before)
            await session.commit()
        ids = dict((await session.execute(
            select(Part.external_id, Part.id).where(Part.source == SEED_SOURCE, Part.external_id.in_(keys))
        )).all())
        return await check_items(session, [(ids[k], qty.get(k, 1)) for k in keys])
    return db.run(go)


def _rule(code):
    return update(CompatibilityRule).where(CompatibilityRule.code == code)


def codes(result):
    return {i.code for i in result.issues}


def test_seed_base_build_is_complete(seeded):
    result = run(seeded, BASE)
    assert result.is_complete and result.issues == ()
    assert result.power.suggested_psu_w == 550


def test_rule_disabled_in_db(seeded):
    keys = ["intel-i5-14400f", *BASE[1:]]
    assert "socket_mismatch" in codes(run(seeded, keys))
    result = run(seeded, keys, _rule("cpu_motherboard_socket").values(is_enabled=False))
    assert "socket_mismatch" not in codes(result) and result.is_compatible


def test_params_from_db(seeded):
    keys = ["amd-ryzen5-7600", "asrock-b650i-lightning-wifi", "kingston-fury-ddr5-32-6000", "asus-tuf-rtx4080s",
            "samsung-990pro-1tb", "corsair-rm850e", "coolermaster-q300l", "noctua-nh-l9a-am5"]
    assert run(seeded, keys).issues == ()
    result = run(seeded, keys, _rule("case_gpu_length").values(params={"warning_margin_mm": 15}))
    assert codes(result) == {"gpu_length_tight"}


def test_severity_from_db(seeded):
    # ASRock B650I: 2 порта SATA и 2 слота M.2. Два SATA-диска помещаются, три уже нет
    keys = [k for k in BASE if k != "msi-b650-gaming-plus-wifi"] + ["asrock-b650i-lightning-wifi", "kingston-nv2-2tb",
                                                                    "samsung-870evo-1tb", "seagate-barracuda-2tb"]
    assert run(seeded, keys).issues == ()

    over = {"samsung-870evo-1tb": 2}  # 2 + 1 = 3 SATA при 2 портах
    result = run(seeded, keys, qty=over)
    assert {i.code for i in result.warnings} == {"sata_ports_exceeded"} and not result.errors

    result = run(seeded, keys, _rule("storage_slots").values(severity=Severity.ERROR), qty=over)
    assert {i.code for i in result.errors} == {"sata_ports_exceeded"} and not result.is_compatible


def test_category_limit_from_db(seeded):
    result = run(seeded, BASE + ["amd-ryzen7-7800x3d"])
    assert "category_limit_exceeded" in {i.code for i in result.errors}


def test_soft_deleted_part_is_rejected(seeded):
    with pytest.raises(UnknownPartsError):
        run(seeded, BASE, update(Part).where(Part.external_id == "deepcool-ak400").values(deleted_at=datetime.now(UTC)))


def test_inactive_part_is_rejected(seeded):
    with pytest.raises(UnknownPartsError):
        run(seeded, BASE, update(Part).where(Part.external_id == "deepcool-ak400").values(is_active=False))
