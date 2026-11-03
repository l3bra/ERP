"""Общие эндпоинты: метаданные, отмена, печать, демо-данные."""

from fastapi import APIRouter, Depends, HTTPException

from .. import config
from ..database import Connection
from ..models import ItemIn
from ..services.inventory import InventoryService
from ..services.undo import UndoManager
from .deps import get_conn, get_inventory

router = APIRouter()


@router.get("/meta")
def meta():
    return {"log_types": config.LOG_TYPES, "quick_amounts": list(config.QUICK_AMOUNTS)}


@router.post("/undo")
def undo_last_change(conn: Connection = Depends(get_conn)):
    return UndoManager(conn).undo_last()


@router.get("/print")
def print_layout(service: InventoryService = Depends(get_inventory)):
    """Раскладка в две колонки для А4, сохраняющая порядок базы."""
    return service.print_layout()


@router.post("/demo")
def demo(service: InventoryService = Depends(get_inventory)):
    """Демо-данные для проверки (существующие позиции пропускаются)."""
    sample = [
        ("Футболка", "Белый", "П-001", "2026-10-01", 40),
        ("Футболка", "Белый", "П-002", "2026-10-15", 25),
        ("Футболка", "Чёрный", "П-001", "2026-10-01", 30),
        ("Худи", "Серый", "П-010", "2026-10-10", 18),
        ("Худи", "Чёрный", "П-010", "2026-10-10", 22),
        ("Кепка", "Синий", "П-020", "2026-10-20", 60),
    ]
    added = 0
    for product, color, batch, d, qty in sample:
        try:
            service.create_item(ItemIn(product=product, color=color, batch=batch, date=d, qty=qty))
            added += 1
        except HTTPException:
            pass
    return {"added": added}
