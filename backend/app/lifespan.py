"""Жизненный цикл приложения: фоновое создание разделителей дней."""

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI

from .database import Database
from .services.journal import JournalService

LOGGER = logging.getLogger(__name__)


async def _daily_divider_scheduler(database: Database):
    while True:
        current = datetime.now()
        next_day = datetime.combine(current.date() + timedelta(days=1), datetime.min.time())
        await asyncio.sleep(max(1, (next_day - current).total_seconds()))
        try:
            with database.connection() as conn:
                JournalService(conn).ensure_daily_dividers()
        except sqlite3.Error:
            LOGGER.exception("Не удалось автоматически добавить разделитель нового дня")


def lifespan_factory(database: Database):
    """Lifespan-обработчик FastAPI с фоновой задачей разделителя дня."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(_daily_divider_scheduler(database))
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return lifespan
