"""Эндпоинты вкладки «МойСклад»: токен, склад, сравнение, сопоставления."""

from fastapi import APIRouter, Depends

from ..models import MoyskladMappingIn, MoyskladStoreIn, MoyskladTokenIn
from ..services.moysklad import MoyskladService
from .deps import get_moysklad

router = APIRouter()


@router.get("/moysklad/config")
def moysklad_config(service: MoyskladService = Depends(get_moysklad)):
    return service.config()


@router.put("/moysklad/token")
def save_moysklad_token(body: MoyskladTokenIn, service: MoyskladService = Depends(get_moysklad)):
    return service.save_token(body.token)


@router.delete("/moysklad/token")
def delete_moysklad_token(service: MoyskladService = Depends(get_moysklad)):
    return service.delete_token()


@router.get("/moysklad/local-groups")
def moysklad_local_groups(service: MoyskladService = Depends(get_moysklad)):
    return service.local_groups()


@router.get("/moysklad/stores")
def list_moysklad_stores(service: MoyskladService = Depends(get_moysklad)):
    return service.stores()


@router.put("/moysklad/store")
def select_moysklad_store(body: MoyskladStoreIn, service: MoyskladService = Depends(get_moysklad)):
    return service.select_store(body.href)


@router.get("/moysklad/compare")
def compare_moysklad_stock(service: MoyskladService = Depends(get_moysklad)):
    return service.compare()


@router.put("/moysklad/mappings")
def save_moysklad_mapping(body: MoyskladMappingIn, service: MoyskladService = Depends(get_moysklad)):
    return service.save_mapping(body)
