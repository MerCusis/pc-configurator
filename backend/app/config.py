"""Настройки приложения. В Docker значения приходят из .env через env_file."""
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    secret_key: str = Field(min_length=32)
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:8080"

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "db"
    postgres_port: int = 5432

    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    @property
    def database_url(self) -> str:
        # URL.create корректно экранирует спецсимволы в пароле (@ : / #)
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _reject_placeholders_in_production(self) -> "Settings":
        if self.is_production:
            weak = [
                name
                for name, value in (
                    ("SECRET_KEY", self.secret_key),
                    ("POSTGRES_PASSWORD", self.postgres_password),
                )
                if value.startswith("change-me")
            ]
            if weak:
                raise ValueError(f"Placeholder values in production: {', '.join(weak)}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
