"""Общие зависимости API: анонимная сессия по Bearer-токену и единый формат ошибок."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.session import AnonSession

SESSION_TTL = timedelta(days=180)
TOUCH_INTERVAL = timedelta(hours=1)


def api_error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    # 32 байта энтропии; в БД попадает только SHA-256
    return secrets.token_urlsafe(32)


async def current_session(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AnonSession:
    if not authorization or not authorization[:7].lower() == "bearer ":
        raise api_error(401, "no_token", "Нужен anon_token: получите его через POST /api/v1/session")
    token = authorization[7:].strip()
    if not token or len(token) > 128:
        raise api_error(401, "invalid_token", "Токен недействителен")
    session = await db.scalar(select(AnonSession).where(AnonSession.token_hash == hash_token(token)))
    now = utcnow()
    if session is None or _aware(session.expires_at) <= now:
        raise api_error(401, "invalid_token", "Токен недействителен или истёк")
    # Продлеваем сессию не чаще раза в час, чтобы не писать в БД на каждый запрос
    if now - _aware(session.last_seen_at) > TOUCH_INTERVAL:
        session.last_seen_at = now
        session.expires_at = now + SESSION_TTL
        await db.commit()
    return session
