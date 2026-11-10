"""Каталог: категории, производители, комплектующие и история цен."""
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger, CheckConstraint, Computed, ForeignKey, Identity, Index, Integer,
    Numeric, SmallInteger, String, UniqueConstraint, false, func, text, true,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

MONEY = Numeric(12, 2)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9_]+$'", name="slug_format"),
        CheckConstraint("max_items BETWEEN 1 AND 16", name="max_items_range"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    is_required: Mapped[bool] = mapped_column(server_default=false())
    # Сколько позиций категории может быть в одной сборке (RAM, накопители > 1)
    max_items: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    def __str__(self) -> str:
        return self.name


class Manufacturer(Base):
    __tablename__ = "manufacturers"
    __table_args__ = (CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="slug_format"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    def __str__(self) -> str:
        return self.name


class Part(TimestampMixin, Base):
    __tablename__ = "parts"
    __table_args__ = (
        # Повторный импорт обновляет позицию, а не создаёт дубль
        UniqueConstraint("source", "external_id"),
        CheckConstraint("jsonb_typeof(specs) = 'object'", name="specs_is_object"),
        CheckConstraint("price IS NULL OR price >= 0", name="price_non_negative"),
        CheckConstraint("power_w IS NULL OR power_w >= 0", name="power_non_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        Index(
            "ix_parts_category_available",
            "category_id",
            postgresql_where=text("deleted_at IS NULL AND is_active"),
        ),
        Index("ix_parts_specs", "specs", postgresql_using="gin", postgresql_ops={"specs": "jsonb_path_ops"}),
        Index("ix_parts_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    manufacturer_id: Mapped[int | None] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="RESTRICT"), index=True
    )
    def __str__(self) -> str:
        return self.name    # Нужны админке для выпадающих списков. raise_on_sql: случайное обращение в API даст понятную ошибку
    category: Mapped["Category"] = relationship(lazy="raise_on_sql")
    manufacturer: Mapped["Manufacturer | None"] = relationship(lazy="raise_on_sql")
    name: Mapped[str] = mapped_column(String(255))
    # Откуда пришла позиция: seed, manual, имя файла импорта и т.п.
    source: Mapped[str] = mapped_column(String(32), server_default=text("'manual'"))
    external_id: Mapped[str | None] = mapped_column(String(128))
    # Характеристики по контракту app.catalog_specs.REQUIRED_SPEC_KEYS
    specs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # Оценка пикового потребления, Вт. Для CPU и GPU обязательна
    power_w: Mapped[int | None] = mapped_column(SmallInteger)
    price: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'RUB'"))
    price_updated_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(server_default=true())
    # Мягкое удаление: сохранённые сборки продолжают ссылаться на деталь
    deleted_at: Mapped[datetime | None]
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(name, ''))", persisted=True),
        deferred=True,
    )


class PartPriceHistory(Base):
    __tablename__ = "part_price_history"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        Index("ix_part_price_history_part_recorded", "part_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    price: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now())
