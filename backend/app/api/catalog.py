"""Эндпоинты каталога: линейки, справочник цветов, заливки таблиц."""

from fastapi import APIRouter, Depends

from ..models import (
    LineIn,
    LineProductColors,
    ProductColorIn,
    ProductColorUpdate,
    StyleTarget,
    TableStyle,
)
from ..services.catalog import CatalogService
from .deps import get_catalog

router = APIRouter()


@router.get("/lines")
def list_lines(service: CatalogService = Depends(get_catalog)):
    return service.list_lines()


@router.put("/lines/{line_name}/product-colors")
def set_line_product_colors(line_name: str, body: LineProductColors,
                            service: CatalogService = Depends(get_catalog)):
    return service.set_line_product_colors(line_name, body)


@router.post("/lines", status_code=201)
def create_line(body: LineIn, service: CatalogService = Depends(get_catalog)):
    return service.create_line(body)


@router.put("/lines")
def update_line(body: LineIn, service: CatalogService = Depends(get_catalog)):
    return service.update_line(body)


@router.delete("/lines/{name}")
def delete_line(name: str, service: CatalogService = Depends(get_catalog)):
    return service.delete_line(name)


@router.get("/product-colors")
def list_product_colors(service: CatalogService = Depends(get_catalog)):
    return service.list_product_colors()


@router.post("/product-colors", status_code=201)
def create_product_color(body: ProductColorIn, service: CatalogService = Depends(get_catalog)):
    return service.create_product_color(body)


@router.delete("/product-colors/{name}")
def delete_product_color(name: str, service: CatalogService = Depends(get_catalog)):
    return service.delete_product_color(name)


@router.put("/product-colors/{name}")
def update_product_color(name: str, body: ProductColorUpdate,
                         service: CatalogService = Depends(get_catalog)):
    return service.update_product_color(name, body)


@router.get("/styles")
def list_styles(service: CatalogService = Depends(get_catalog)):
    return service.list_styles()


@router.put("/styles")
def save_style(body: TableStyle, service: CatalogService = Depends(get_catalog)):
    return service.save_style(body)


@router.delete("/styles")
def delete_style(body: StyleTarget, service: CatalogService = Depends(get_catalog)):
    return service.delete_style(body)
