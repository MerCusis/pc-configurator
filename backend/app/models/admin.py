"""Администраторы, задания импорта и журнал действий."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger, CheckConstraint, ForeignKey, Identity, Index, Integer,
    SmallInteger, String, Text, func, text, true,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, str_enum
from app.models.enums import ImportFormat, ImportStatus


class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = (CheckConstraint("username ~ '^[a-z0-9_.-]{3,64}$'", name="username_format"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(server_default=true())
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    locked_until: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login_at: Mapped[datetime | None]


class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(stats) = 'object'", name="stats_is_object"),
        # Два импорта одновременно не запустятся даже при гонке воркеров
        Index(
            "uq_import_jobs_single_running",
            "status",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[ImportFormat] = mapped_column(str_enum(ImportFormat, "file_format"))
    status: Mapped[ImportStatus] = mapped_column(
        str_enum(ImportStatus, "status"), server_default=text("'pending'")
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_is_object"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
