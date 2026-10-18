"""Правила совместимости. Логика в коде (этап 3), здесь включение и параметры."""
from typing import Any

from sqlalchemy import CheckConstraint, Identity, Integer, String, Text, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, str_enum
from app.models.enums import Severity


class CompatibilityRule(TimestampMixin, Base):
    __tablename__ = "compatibility_rules"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z0-9_]+$'", name="code_format"),
        CheckConstraint("jsonb_typeof(params) = 'object'", name="params_is_object"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(str_enum(Severity, "severity"))
    is_enabled: Mapped[bool] = mapped_column(server_default=true())
    # Пороговые значения, которые админ может менять без релиза
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
