"""Скрипт create_admin: валидация, создание, сброс пароля и блокировки."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import Admin
from app.scripts.create_admin import upsert_admin, validate
from app.security import verify_password

GOOD = "correct-horse-battery"


@pytest.mark.parametrize("username,password", [
    ("ad", GOOD),            # короткий логин
    ("Admin", GOOD),         # заглавные
    ("adm in", GOOD),        # пробел
    ("admin", "short"),      # короткий пароль
])
def test_validate_rejects(username, password):
    with pytest.raises(ValueError):
        validate(username, password)


def test_validate_accepts():
    validate("admin.main-1", GOOD)


@pytest.mark.db
def test_create_and_reject_duplicate(db):
    async def create(s):
        return await upsert_admin(s, "admin", GOOD)
    assert db.run(create) == "created"

    async def dup(s):
        with pytest.raises(ValueError, match="уже существует"):
            await upsert_admin(s, "admin", GOOD + "x")
    db.run(dup)

    async def load(s):
        return await s.scalar(select(Admin).where(Admin.username == "admin"))
    admin = db.run(load)
    assert admin.password_hash.startswith("$argon2id$")
    assert GOOD not in admin.password_hash
    assert verify_password(admin.password_hash, GOOD)


@pytest.mark.db
def test_reset_password_unlocks(db):
    async def prepare(s):
        await upsert_admin(s, "admin", GOOD)
        await s.execute(update(Admin).values(
            failed_login_count=5, locked_until=datetime.now(UTC) + timedelta(hours=1), is_active=False,
        ))
        await s.commit()
        return await upsert_admin(s, "admin", "new-strong-password", reset=True)
    assert db.run(prepare) == "updated"

    async def load(s):
        return await s.scalar(select(Admin).where(Admin.username == "admin"))
    admin = db.run(load)
    assert admin.failed_login_count == 0 and admin.locked_until is None and admin.is_active
    assert verify_password(admin.password_hash, "new-strong-password")
    assert not verify_password(admin.password_hash, GOOD)
