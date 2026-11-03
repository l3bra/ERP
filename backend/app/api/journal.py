"""Эндпоинты вкладки «Журнал»: строки, разделители, месяцы, общие примечания."""

from typing import Optional

from fastapi import APIRouter, Depends

from ..models import Divider, LogNoteGroupIn, LogNoteGroupUpdate, LogUpdate
from ..services.journal import JournalService
from ..utils import dump
from .deps import get_journal

router = APIRouter()


@router.get("/logs/months")
def log_months(service: JournalService = Depends(get_journal)):
    """Список месяцев журнала (текущий создаётся автоматически)."""
    return service.months()


@router.get("/logs")
def get_logs(month: Optional[str] = None, service: JournalService = Depends(get_journal)):
    """Записи журнала за месяц (по умолчанию текущий), от старых к новым."""
    return service.list_logs(month)


@router.post("/logs/divider", status_code=201)
def add_divider(body: Divider, service: JournalService = Depends(get_journal)):
    """Добавляет идемпотентный разделитель дня либо разделитель инвентаризации."""
    return service.add_divider(body.kind)


@router.post("/logs/note-groups", status_code=201)
def create_log_note_group(body: LogNoteGroupIn, service: JournalService = Depends(get_journal)):
    return service.create_note_group(body)


@router.put("/logs/note-groups/{group_id}")
def update_log_note_group(group_id: int, body: LogNoteGroupUpdate,
                          service: JournalService = Depends(get_journal)):
    return service.update_note_group(group_id, dump(body))


@router.delete("/logs/note-groups/{group_id}")
def delete_log_note_group(group_id: int, service: JournalService = Depends(get_journal)):
    return service.delete_note_group(group_id)


@router.put("/logs/{log_id}")
def update_log(log_id: int, body: LogUpdate, service: JournalService = Depends(get_journal)):
    """Правка строки журнала. Остатки в базе НЕ меняются — правится только запись."""
    return service.update_log(log_id, dump(body))


@router.delete("/logs/{log_id}")
def delete_log(log_id: int, service: JournalService = Depends(get_journal)):
    """Удаляет одну запись журнала. Вкладки месяцев не удаляются никогда."""
    return service.delete_log(log_id)
