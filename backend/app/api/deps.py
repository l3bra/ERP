"""Dependency injection для обработчиков: подключение к БД и сервисы."""

from typing import Iterator

from fastapi import Depends, Request

from ..database import Connection, Database
from ..services.catalog import CatalogService
from ..services.inventory import InventoryService
from ..services.journal import JournalService
from ..services.moysklad import MoyskladService


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_conn(request: Request) -> Iterator[Connection]:
    with request.app.state.database.connection() as conn:
        yield conn


def get_inventory(conn: Connection = Depends(get_conn)) -> InventoryService:
    return InventoryService(conn)


def get_journal(conn: Connection = Depends(get_conn)) -> JournalService:
    return JournalService(conn)


def get_catalog(conn: Connection = Depends(get_conn)) -> CatalogService:
    return CatalogService(conn)


def get_moysklad(conn: Connection = Depends(get_conn)) -> MoyskladService:
    return MoyskladService(conn)
