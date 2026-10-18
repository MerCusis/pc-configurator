"""Сборки пользователей и их состав."""
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, ForeignKey, Identity, Integer, SmallInteger,
    String, Text, UniqueConstraint, false, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.catalog import MONEY


class Build(TimestampMixin, Base):
    __tablename__ = "builds"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("description IS NULL OR char_length(description) <= 2000", name="description_length"),
        # Публичная сборка всегда доступна по короткой ссылке
        CheckConstraint("NOT is_public OR share_slug IS NOT NULL", name="public_requires_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("anon_sessions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(server_default=false())
    share_slug: Mapped[str | None] = mapped_column(String(16), unique=True)
    # Снимок на момент сохранения; актуальная цена считается по parts.price
    total_price: Mapped[Decimal | None] = mapped_column(MONEY)
    total_power_w: Mapped[int | None] = mapped_column(Integer)


class BuildItem(Base):
    __tablename__ = "build_items"
    __table_args__ = (
        UniqueConstraint("build_id", "part_id"),
        CheckConstraint("quantity BETWEEN 1 AND 16", name="quantity_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    build_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("builds.id", ondelete="CASCADE"))
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    price_snapshot: Mapped[Decimal | None] = mapped_column(MONEY)
