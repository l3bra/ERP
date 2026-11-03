"""Эндпоинты вкладки «База»: позиции и изменение остатков."""

from fastapi import APIRouter, Depends

from ..models import Amount, ItemIn, ItemOrder, ItemUpdate
from ..services.inventory import InventoryService
from .deps import get_inventory

router = APIRouter()


@router.get("/items")
def list_items(service: InventoryService = Depends(get_inventory)):
    return service.list_items()


@router.put("/items/order")
def reorder_items(body: ItemOrder, service: InventoryService = Depends(get_inventory)):
    return service.reorder_items(body)


@router.post("/items", status_code=201)
def create_item(body: ItemIn, service: InventoryService = Depends(get_inventory)):
    """Новая партия. В журнал пишется НОВАЯ ПАРТИЯ."""
    return service.create_item(body)


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate, service: InventoryService = Depends(get_inventory)):
    """Изменения реквизитов сохраняются в базе; в журнал попадают только изменения количества."""
    return service.update_item(item_id, body)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, service: InventoryService = Depends(get_inventory)):
    return service.delete_item(item_id)


@router.post("/items/{item_id}/quick/{amount}")
def quick_consume(item_id: int, amount: int, service: InventoryService = Depends(get_inventory)):
    """Кнопки быстрого списания: 1 / 6 / 9 / 12."""
    return service.quick_consume(item_id, amount)


@router.post("/items/{item_id}/consume")
def manual_consume(item_id: int, body: Amount, service: InventoryService = Depends(get_inventory)):
    return service.consume(item_id, body.amount)


@router.post("/items/{item_id}/receive")
def receive(item_id: int, body: Amount, service: InventoryService = Depends(get_inventory)):
    return service.receive(item_id, body.amount)
