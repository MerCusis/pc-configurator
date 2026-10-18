from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ImportFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    XLSX = "xlsx"


class ImportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
