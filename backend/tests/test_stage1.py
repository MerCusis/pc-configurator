import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import make_url

import app.main as main
from app.config import Settings

BASE = {"secret_key": "x" * 40, "postgres_user": "u", "postgres_password": "p", "postgres_db": "d"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _fake_checks(monkeypatch, db_ok: bool, redis_ok: bool) -> None:
    async def fake_db() -> bool:
        return db_ok

    async def fake_redis() -> bool:
        return redis_ok

    monkeypatch.setattr(main, "check_db", fake_db)
    monkeypatch.setattr(main, "check_redis", fake_redis)


def test_liveness(client):
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "alive"}


@pytest.mark.parametrize(
    ("db_ok", "redis_ok", "code", "status"),
    [(True, True, 200, "ok"), (False, True, 503, "degraded"), (True, False, 503, "degraded")],
)
def test_readiness(client, monkeypatch, db_ok, redis_ok, code, status):
    _fake_checks(monkeypatch, db_ok, redis_ok)
    r = client.get("/api/v1/health")
    assert r.status_code == code
    body = r.json()
    assert body["status"] == status
    assert body["db"] is db_ok and body["redis"] is redis_ok


def test_openapi_available_in_dev(client):
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_database_url_escapes_password(monkeypatch):
    # Хост/порт из окружения (локальный запуск тестов) не должны влиять на проверку дефолтов
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    s = Settings(_env_file=None, **{**BASE, "postgres_password": "p@ss:w/rd#1"})
    url = make_url(s.database_url)
    assert url.drivername == "postgresql+asyncpg"
    assert url.password == "p@ss:w/rd#1"
    assert url.host == "db" and url.port == 5432 and url.database == "d"


def test_short_secret_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**BASE, "secret_key": "short"})


def test_production_rejects_placeholders():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**BASE, "app_env": "production", "secret_key": "change-me-" + "x" * 40})


def test_cors_origins_parsing():
    s = Settings(_env_file=None, **{**BASE, "cors_origins": "http://a, http://b ,"})
    assert s.cors_origins_list == ["http://a", "http://b"]


def test_celery_ping_task():
    from app.tasks.celery_app import celery_app
    from app.tasks.system import ping

    assert "system.ping" in celery_app.tasks
    assert ping.apply().get() == "pong"  # локальный запуск, брокер не нужен
