"""Все модели импортируются здесь, чтобы Alembic видел полную схему."""
from app.models.admin import Admin, AuditLog, ImportJob
from app.models.base import Base
from app.models.build import Build, BuildItem
from app.models.catalog import Category, Manufacturer, Part, PartPriceHistory
from app.models.enums import ImportFormat, ImportStatus, Severity
from app.models.rules import CompatibilityRule
from app.models.session import AnonSession

__all__ = [
    "Admin", "AnonSession", "AuditLog", "Base", "Build", "BuildItem", "Category",
    "CompatibilityRule", "ImportFormat", "ImportJob", "ImportStatus", "Manufacturer",
    "Part", "PartPriceHistory", "Severity",
]
