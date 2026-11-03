"""Складской учёт: сборка FastAPI-приложения.

    items      -> остатки (вкладка «База»)
    logs       -> журнал операций и разделителей (вкладка «Журнал»)
    /print     -> данные для печати на А4

Архитектура: main.py -> create_app() -> Database + Services + Routers.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import catalog, common, items, journal, moysklad
from .database import Database
from .lifespan import lifespan_factory
from .services.journal import JournalService


def _frontend():
    """Раздаёт собранный фронтенд (Vue) либо прежний одностраничный интерфейс."""
    if config.FRONTEND_DIST_INDEX.is_file():
        return FileResponse(config.FRONTEND_DIST_INDEX, media_type="text/html")
    if config.FRONTEND_LEGACY_INDEX.is_file():
        return FileResponse(config.FRONTEND_LEGACY_INDEX, media_type="text/html")
    if config.FRONTEND_PATH.is_file():
        return FileResponse(config.FRONTEND_PATH, media_type="text/html")
    raise HTTPException(500, "Файл интерфейса frontend не найден")


def create_app(database: Database | None = None) -> FastAPI:
    """Создаёт и инициализирует приложение: схема БД, роутеры, статика."""
    database = database or Database()
    database.initialize()
    with database.connection() as conn:
        JournalService(conn).ensure_months()

    app = FastAPI(title="Warehouse", lifespan=lifespan_factory(database))
    app.state.database = database
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],     # локальная разработка
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(common.router)
    app.include_router(items.router)
    app.include_router(journal.router)
    app.include_router(catalog.router)
    app.include_router(moysklad.router)
    app.get("/", include_in_schema=False)(_frontend)
    if config.FRONTEND_DIST_ASSETS.is_dir():
        app.mount("/assets", StaticFiles(directory=str(config.FRONTEND_DIST_ASSETS)),
                  name="frontend-assets")
    return app
