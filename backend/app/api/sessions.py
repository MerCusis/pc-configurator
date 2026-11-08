"""Выдача анонимного токена гостя."""
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SESSION_TTL, api_error, current_session, hash_token, new_token, utcnow
from app.database import get_db
from app.models.build import Build
from app.models.session import AnonSession
from app.redis_client import redis_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["session"])

SESSIONS_PER_HOUR_PER_IP = 30
MAX_BUILDS_PER_SESSION = 15


async def session_rate_limit(request: Request) -> None:
    """Не больше 30 новых сессий в час с одного IP. Если Redis недоступен, лимит не применяется."""
    ip = request.client.host if request.client else "unknown"
    key = f"rl:session:{ip}"
    try:
        async with redisclient.pipeline(transaction=True) as pipe:
            pipe.set(key, 0, ex=3600, nx=True)
            pipe.incr(key)
            _, count = await pipe.execute()
    except Exception:  # noqa: BLE001
        logger.warning("Rate limit skipped: Redis unavailable", exc_info=True)
        return
    if count > SESSIONS_PER_HOUR_PER_IP:
        raise api_error(429, "too_many_sessions", "Слишком много новых сессий, попробуйте позже")


@router.post("/session", status_code=201)
async def create_session(_: None = Depends(session_rate_limit), db: AsyncSession = Depends(get_db)):
    token = new_token()
    expires = utcnow() + SESSION_TTL
    db.add(AnonSession(token_hash=hash_token(token), expires_at=expires))
    await db.commit()
    return {"anon_token": token, "token_type": "bearer", "expires_at": expires.isoformat(),
            "builds_limit": MAX_BUILDS_PER_SESSION}


@router.get("/session")
async def read_session(s: AnonSession = Depends(current_session), db: AsyncSession = Depends(get_db)):
    count = await db.scalar(select(func.count()).select_from(Build).where(Build.session_id == s.id))
    return {"expires_at": s.expires_at.isoformat(), "builds_count": count, "builds_limit": MAX_BUILDS_PER_SESSION}
