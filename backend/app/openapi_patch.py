"""Дополнение OpenAPI-схемы: Bearer-авторизация для Swagger и адреса серверов.

Подключение в app/main.py сразу после создания app:
    from app.openapi_patch import install_openapi
    install_openapi(app)
Бизнес-логику не меняет: эндпоинты по-прежнему читают заголовок Authorization.
"""
import os
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from app.openapi_patch import install_openapi

SCHEME = "AnonToken"


def install_openapi(app: FastAPI) -> None:
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        comps = schema.setdefault("components", {})
        comps.setdefault("securitySchemes", {})[SCHEME] = {
            "type": "http",
            "scheme": "bearer",
            "description": "anon_token из ответа POST /api/v1/session",
        }
        for ops in schema.get("paths", {}).values():
            for op in ops.values():
                params = op.get("parameters", [])
                auth = [p for p in params
                        if p.get("in") == "header" and p.get("name", "").lower() == "authorization"]
                if auth:
                    # Заголовок теперь передаётся через кнопку Authorize, а не как поле формы
                    op["parameters"] = [p for p in params if p not in auth]
                    op["security"] = [{SCHEME: []}]
        servers = [u.strip() for u in os.getenv("OPENAPI_SERVERS", "").split(",") if u.strip()]
        if servers:
            schema["servers"] = [{"url": u} for u in servers]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
    install_openapi(app)