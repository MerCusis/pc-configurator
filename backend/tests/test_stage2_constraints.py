"""Ограничения БД: защита данных работает даже в обход API."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.models import AnonSession, Build, BuildItem, Category, ImportJob, Part
from app.models.enums import ImportFormat, ImportStatus

pytestmark = pytest.mark.db


async def _category(s) -> Category:
    cat = Category(slug="cpu", name="Процессоры", sort_order=10, is_required=True, max_items=1)
    s.add(cat)
    await s.flush()
    return cat


async def _part(s, **kw) -> Part:
    cat = await _category(s)
    values = {"name": "Test CPU", "source": "test", "external_id": str(uuid.uuid4()),
              "specs": {"socket": "AM5"}, "price": Decimal("100.00"), "currency": "RUB"}
    values.update(kw)
    part = Part(category_id=cat.id, **values)
    s.add(part)
    return part


async def _session(s) -> AnonSession:
    sess = AnonSession(token_hash="a" * 64, expires_at=datetime.now(UTC) + timedelta(days=90))
    s.add(sess)
    await s.flush()
    return sess


def _expect_violation(db, prepare):
    async def go(s):
        await prepare(s)
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()
    db.run(go)


@pytest.mark.parametrize("bad", [
    {"price": Decimal("-1")},
    {"power_w": -5},
    {"currency": "rub"},
    {"specs": [1, 2]},
])
def test_part_check_constraints(db, bad):
    _expect_violation(db, lambda s: _part(s, **bad))


def test_part_unique_source_external_id(db):
    async def prepare(s):
        part = await _part(s, external_id="dup")
        await s.flush()
        s.add(Part(category_id=part.category_id, name="Copy", source="test", external_id="dup"))
    _expect_violation(db, prepare)


def test_only_one_running_import(db):
    fmt = list(ImportFormat)[0]

    async def prepare(s):
        s.add(ImportJob(filename="a.csv", file_format=fmt, status=ImportStatus("running")))
        await s.flush()
        s.add(ImportJob(filename="b.csv", file_format=fmt, status=ImportStatus("running")))
    _expect_violation(db, prepare)


def test_finished_imports_do_not_block(db):
    fmt = list(ImportFormat)[0]
    statuses = [st for st in ImportStatus if st.value != "running"]

    async def go(s):
        for st in statuses * 2:
            s.add(ImportJob(filename="x.csv", file_format=fmt, status=st))
        s.add(ImportJob(filename="r.csv", file_format=fmt, status=ImportStatus("running")))
        await s.commit()
        return await s.scalar(select(func.count()).select_from(ImportJob))
    assert db.run(go) == len(statuses) * 2 + 1


def test_token_hash_must_be_sha256(db):
    async def prepare(s):
        s.add(AnonSession(token_hash="plain-token", expires_at=datetime.now(UTC)))
    _expect_violation(db, prepare)


def test_public_build_requires_slug(db):
    async def prepare(s):
        sess = await _session(s)
        s.add(Build(session_id=sess.id, name="Игровой ПК", is_public=True, share_slug=None))
    _expect_violation(db, prepare)


def test_build_item_quantity_range(db):
    async def prepare(s):
        sess = await _session(s)
        part = await _part(s)
        build = Build(session_id=sess.id, name="ПК")
        s.add(build)
        await s.flush()
        s.add(BuildItem(build_id=build.id, part_id=part.id, quantity=0))
    _expect_violation(db, prepare)


def test_part_in_build_cannot_be_hard_deleted(db):
    async def prepare(s):
        sess = await _session(s)
        part = await _part(s)
        build = Build(session_id=sess.id, name="ПК")
        s.add(build)
        await s.flush()
        s.add(BuildItem(build_id=build.id, part_id=part.id, quantity=1))
        await s.commit()
        # FK с ON DELETE RESTRICT срабатывает сразу на DELETE, а не на flush/commit
        with pytest.raises(IntegrityError):
            await s.execute(delete(Part).where(Part.id == part.id))
        await s.rollback()
    db.run(prepare)


def test_session_delete_cascades_to_builds(db):
    async def go(s):
        sess = await _session(s)
        part = await _part(s)
        build = Build(session_id=sess.id, name="ПК")
        s.add(build)
        await s.flush()
        s.add(BuildItem(build_id=build.id, part_id=part.id, quantity=2))
        await s.commit()
        await s.execute(delete(AnonSession).where(AnonSession.id == sess.id))
        await s.commit()
        builds = await s.scalar(select(func.count()).select_from(Build))
        items = await s.scalar(select(func.count()).select_from(BuildItem))
        parts = await s.scalar(select(func.count()).select_from(Part))
        return builds, items, parts
    assert db.run(go) == (0, 0, 1)
